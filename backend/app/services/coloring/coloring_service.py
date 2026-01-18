"""Coloring generation service.

This service handles business logic for coloring version management.
Tasks should be dispatched by API routes, not by this service.
"""

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.models.coloring import ColoringVersion
from app.models.enums import ColoringProcessingStatus
from app.models.order import Image, LineItem, Order
from app.services.coloring.exceptions import (
    ColoringVersionNotFound,
    NoImagesToProcess,
    VersionNotInErrorState,
)
from app.services.orders.exceptions import (
    ImageNotDownloaded,
    ImageNotFound,
    OrderNotFound,
)

logger = structlog.get_logger(__name__)


class ColoringService:
    """Service for coloring version management.

    Note: This service does NOT dispatch Dramatiq tasks.
    API routes should call service methods and dispatch tasks separately.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_version(
        self,
        image_id: int,
        *,
        megapixels: float = 1.0,
        steps: int = 4,
    ) -> ColoringVersion:
        """Create a new coloring version for an image.

        Returns the created version. Caller is responsible for dispatching the task.
        """
        # Load image with line_item and order
        statement = (
            select(Image)
            .options(selectinload(Image.line_item).selectinload(LineItem.order))  # type: ignore[arg-type]
            .where(Image.id == image_id)
        )
        result = await self.session.execute(statement)
        image = result.scalars().first()

        if not image:
            raise ImageNotFound()

        if not image.file_ref:
            raise ImageNotDownloaded()

        next_version = await self._get_next_version(image_id)

        coloring_version = ColoringVersion(
            image_id=image_id,
            version=next_version,
            status=ColoringProcessingStatus.QUEUED,
            megapixels=megapixels,
            steps=steps,
        )
        self.session.add(coloring_version)
        await self.session.flush()

        # Auto-select the new version
        assert coloring_version.id is not None
        image.selected_coloring_id = coloring_version.id

        await self.session.commit()

        logger.info(
            "Created coloring version",
            image_id=image_id,
            version_id=coloring_version.id,
            version=next_version,
        )

        return coloring_version

    async def create_versions_for_order(
        self,
        order_id: str,
        *,
        megapixels: float = 1.0,
        steps: int = 4,
    ) -> list[int]:
        """Create coloring versions for all eligible images in order.

        Returns list of created version IDs. Caller is responsible for dispatching tasks.
        """
        # Get order with all images and their coloring versions
        statement = (
            select(Order)
            .options(
                selectinload(Order.line_items)  # type: ignore[arg-type]
                .selectinload(LineItem.images)  # type: ignore[arg-type]
                .selectinload(Image.coloring_versions)  # type: ignore[arg-type]
            )
            .where(Order.id == order_id)
        )
        result = await self.session.execute(statement)
        order = result.scalars().first()
        if not order:
            raise OrderNotFound()

        # Collect images that need coloring generation
        images_to_process: list[Image] = []
        for li in order.line_items:
            for img in li.images:
                if not img.file_ref:
                    continue
                has_completed = any(cv.status == ColoringProcessingStatus.COMPLETED for cv in img.coloring_versions)
                if has_completed:
                    continue
                is_processing = any(
                    cv.status in (ColoringProcessingStatus.QUEUED, ColoringProcessingStatus.PROCESSING)
                    for cv in img.coloring_versions
                )
                if is_processing:
                    continue
                images_to_process.append(img)

        if not images_to_process:
            raise NoImagesToProcess()

        version_ids: list[int] = []
        for image in images_to_process:
            assert image.id is not None
            next_version = await self._get_next_version(image.id)

            coloring_version = ColoringVersion(
                image_id=image.id,
                version=next_version,
                status=ColoringProcessingStatus.QUEUED,
                megapixels=megapixels,
                steps=steps,
            )
            self.session.add(coloring_version)
            await self.session.flush()

            assert coloring_version.id is not None
            image.selected_coloring_id = coloring_version.id
            version_ids.append(coloring_version.id)

        await self.session.commit()

        logger.info(
            "Created coloring versions for order",
            order_id=order_id,
            count=len(version_ids),
        )

        return version_ids

    async def prepare_retry(self, version_id: int) -> ColoringVersion:
        """Prepare a failed coloring version for retry.

        Returns the updated version. Caller is responsible for dispatching the task.
        """
        coloring = await self.session.get(ColoringVersion, version_id)
        if not coloring:
            raise ColoringVersionNotFound()
        if coloring.status != ColoringProcessingStatus.ERROR:
            raise VersionNotInErrorState()

        coloring.status = ColoringProcessingStatus.QUEUED
        await self.session.commit()

        logger.info("Prepared coloring version for retry", version_id=version_id)

        return coloring

    async def _get_next_version(self, image_id: int) -> int:
        """Get the next version number for a coloring version."""
        result = await self.session.execute(
            select(func.coalesce(func.max(ColoringVersion.version), 0)).where(ColoringVersion.image_id == image_id)
        )
        max_version = result.scalar() or 0
        return max_version + 1

    @staticmethod
    async def get_incomplete_versions(session: AsyncSession) -> list[int]:
        """Get IDs of coloring versions stuck in intermediate states.

        Used by task recovery to find tasks that were interrupted.
        Excludes versions that already have file_ref (completed but status not updated).
        """
        result = await session.execute(
            select(ColoringVersion.id).where(
                ColoringVersion.status.in_(ColoringProcessingStatus.intermediate_states()),  # type: ignore[attr-defined]
                ColoringVersion.file_ref == None,  # noqa: E711 - SQLAlchemy None check
            )
        )
        return [row[0] for row in result.fetchall()]
