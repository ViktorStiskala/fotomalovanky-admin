"""SVG vectorization service.

This service handles business logic for SVG version management.
Tasks should be dispatched by API routes, not by this service.
"""

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.models.coloring import ColoringVersion, SvgVersion
from app.models.enums import ColoringProcessingStatus, SvgProcessingStatus
from app.models.order import Image, LineItem, Order
from app.services.coloring.exceptions import (
    NoColoringAvailable,
    NoImagesToProcess,
    SvgVersionNotFound,
    VersionNotInErrorState,
)
from app.services.orders.exceptions import ImageNotFound, OrderNotFound

logger = structlog.get_logger(__name__)


class VectorizerService:
    """Service for SVG vectorization management.

    Note: This service does NOT dispatch Dramatiq tasks.
    API routes should call service methods and dispatch tasks separately.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create_version(
        self,
        image_id: int,
        *,
        shape_stacking: str = "stacked",
        group_by: str = "color",
    ) -> SvgVersion:
        """Create a new SVG version for an image.

        Returns the created version. Caller is responsible for dispatching the task.
        """
        # Get image with coloring versions, line_item and order
        statement = (
            select(Image)
            .options(
                selectinload(Image.coloring_versions),  # type: ignore[arg-type]
                selectinload(Image.line_item).selectinload(LineItem.order),  # type: ignore[arg-type]
            )
            .where(Image.id == image_id)
        )
        result = await self.session.execute(statement)
        image = result.scalars().first()

        if not image:
            raise ImageNotFound()

        # Find coloring version to use
        coloring_to_use = self._find_coloring_for_svg(image)
        if not coloring_to_use:
            raise NoColoringAvailable()

        next_version = await self._get_next_version(image_id)

        svg_version = SvgVersion(
            coloring_version_id=coloring_to_use.id,
            version=next_version,
            status=SvgProcessingStatus.QUEUED,
            shape_stacking=shape_stacking,
            group_by=group_by,
        )
        self.session.add(svg_version)
        await self.session.flush()

        # Auto-select the new version
        assert svg_version.id is not None
        image.selected_svg_id = svg_version.id

        await self.session.commit()

        logger.info(
            "Created SVG version",
            image_id=image_id,
            version_id=svg_version.id,
            version=next_version,
        )

        return svg_version

    async def create_versions_for_order(
        self,
        order_id: str,
        *,
        shape_stacking: str = "stacked",
        group_by: str = "color",
    ) -> list[int]:
        """Create SVG versions for all eligible images in order.

        Returns list of created version IDs. Caller is responsible for dispatching tasks.
        """
        # Get order with all images, coloring versions, and their SVG versions
        statement = (
            select(Order)
            .options(
                selectinload(Order.line_items)  # type: ignore[arg-type]
                .selectinload(LineItem.images)  # type: ignore[arg-type]
                .selectinload(Image.coloring_versions)  # type: ignore[arg-type]
                .selectinload(ColoringVersion.svg_versions)  # type: ignore[arg-type]
            )
            .where(Order.id == order_id)
        )
        result = await self.session.execute(statement)
        order = result.scalars().first()
        if not order:
            raise OrderNotFound()

        version_ids: list[int] = []
        for li in order.line_items:
            for img in li.images:
                coloring_to_use = self._find_coloring_for_svg(img)
                if not coloring_to_use:
                    continue

                # Check if image already has any completed SVG
                has_completed_svg = any(
                    sv.status == SvgProcessingStatus.COMPLETED for cv in img.coloring_versions for sv in cv.svg_versions
                )
                if has_completed_svg:
                    continue

                # Check if any SVG is currently processing
                is_svg_processing = any(
                    sv.status in (SvgProcessingStatus.QUEUED, SvgProcessingStatus.PROCESSING)
                    for cv in img.coloring_versions
                    for sv in cv.svg_versions
                )
                if is_svg_processing:
                    continue

                assert img.id is not None
                assert coloring_to_use.id is not None
                next_version = await self._get_next_version(img.id)

                svg_version = SvgVersion(
                    coloring_version_id=coloring_to_use.id,
                    version=next_version,
                    status=SvgProcessingStatus.QUEUED,
                    shape_stacking=shape_stacking,
                    group_by=group_by,
                )
                self.session.add(svg_version)
                await self.session.flush()

                assert svg_version.id is not None
                img.selected_svg_id = svg_version.id
                version_ids.append(svg_version.id)

        if not version_ids:
            raise NoImagesToProcess()

        await self.session.commit()

        logger.info(
            "Created SVG versions for order",
            order_id=order_id,
            count=len(version_ids),
        )

        return version_ids

    async def prepare_retry(self, version_id: int) -> SvgVersion:
        """Prepare a failed SVG version for retry.

        Returns the updated version. Caller is responsible for dispatching the task.
        """
        svg = await self.session.get(SvgVersion, version_id)
        if not svg:
            raise SvgVersionNotFound()
        if svg.status != SvgProcessingStatus.ERROR:
            raise VersionNotInErrorState()

        svg.status = SvgProcessingStatus.QUEUED
        await self.session.commit()

        logger.info("Prepared SVG version for retry", version_id=version_id)

        return svg

    def _find_coloring_for_svg(self, image: Image) -> ColoringVersion | None:
        """Find the best coloring version to use for SVG generation.

        Prefers the selected coloring version, falls back to latest completed.
        """
        # Try selected coloring first
        if image.selected_coloring_id:
            for cv in image.coloring_versions:
                if cv.id == image.selected_coloring_id and cv.status == ColoringProcessingStatus.COMPLETED:
                    return cv

        # Fall back to latest completed coloring
        completed = [cv for cv in image.coloring_versions if cv.status == ColoringProcessingStatus.COMPLETED]
        if completed:
            return max(completed, key=lambda x: x.version)

        return None

    async def _get_next_version(self, image_id: int) -> int:
        """Get the next version number for an SVG version (across all colorings for this image)."""
        # Get all coloring versions for this image
        coloring_ids_result = await self.session.execute(
            select(ColoringVersion.id).where(ColoringVersion.image_id == image_id)
        )
        coloring_ids = [row[0] for row in coloring_ids_result.fetchall()]

        if not coloring_ids:
            return 1

        result = await self.session.execute(
            select(func.coalesce(func.max(SvgVersion.version), 0)).where(
                SvgVersion.coloring_version_id.in_(coloring_ids)  # type: ignore[attr-defined]
            )
        )
        max_version = result.scalar() or 0
        return max_version + 1

    @staticmethod
    async def get_incomplete_versions(session: AsyncSession) -> list[int]:
        """Get IDs of SVG versions stuck in intermediate states.

        Used by task recovery to find tasks that were interrupted.
        Excludes versions that already have file_ref (completed but status not updated).
        """
        result = await session.execute(
            select(SvgVersion.id).where(
                SvgVersion.status.in_(SvgProcessingStatus.intermediate_states()),  # type: ignore[attr-defined]
                SvgVersion.file_ref == None,  # noqa: E711 - SQLAlchemy None check
            )
        )
        return [row[0] for row in result.fetchall()]
