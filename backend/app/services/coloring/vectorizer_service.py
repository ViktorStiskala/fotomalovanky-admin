"""SVG vectorization service.

This service handles business logic for SVG version management.
Tasks should be dispatched by API routes, not by this service.
"""

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.db.mercure_protocol import mercure_autotrack
from app.db.tracked_session import TrackedAsyncSession
from app.models.coloring import ColoringVersion, SvgVersion
from app.models.enums import ColoringProcessingStatus, SvgProcessingStatus
from app.models.order import Image, LineItem, Order
from app.services.coloring.exceptions import (
    NoColoringAvailable,
    NoImagesToProcess,
    SvgVersionNotFound,
    VersionNotInErrorState,
    VersionOwnershipError,
)
from app.services.exceptions import UnexpectedStatusError
from app.services.mercure.events import ImageUpdateEvent
from app.services.orders.exceptions import ImageNotFound, OrderNotFound
from app.tasks.utils.processing_lock import RecordLock, RecordNotFoundError

logger = structlog.get_logger(__name__)


@mercure_autotrack(ImageUpdateEvent)
class VectorizerService:
    """Service for SVG vectorization management.

    Note: This service does NOT dispatch Dramatiq tasks.
    API routes should call service methods and dispatch tasks separately.
    """

    session: TrackedAsyncSession  # Required by MercureTrackable protocol

    def __init__(self, session: TrackedAsyncSession):
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
            image_id=image.id,  # Direct reference for queries
            coloring_version_id=coloring_to_use.id,
            version=next_version,
            status=SvgProcessingStatus.QUEUED,
            shape_stacking=shape_stacking,
            group_by=group_by,
        )
        self.session.add(svg_version)
        await self.session.flush()

        # Note: selected_svg_id is set by svg_generation_service when processing completes
        assert svg_version.id is not None

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
                    image_id=img.id,  # Direct reference for queries
                    coloring_version_id=coloring_to_use.id,
                    version=next_version,
                    status=SvgProcessingStatus.QUEUED,
                    shape_stacking=shape_stacking,
                    group_by=group_by,
                )
                self.session.add(svg_version)
                await self.session.flush()

                # Note: selected_svg_id is set by svg_generation_service when processing completes
                assert svg_version.id is not None
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

    async def prepare_retry(
        self, version_id: int, *, order_id: str, image_id: int
    ) -> SvgVersion:
        """Prepare a failed SVG version for retry.

        Uses RecordLock to prevent race conditions with task recovery.
        Validates ownership inside the lock for atomic validation.

        Returns the updated version. Caller is responsible for dispatching the task.
        """
        # Set Mercure context FIRST (before any tracked field changes)
        self.session.set_mercure_context(Order.id == order_id, Image.id == image_id)  # type: ignore[arg-type]

        lock = RecordLock(
            session=self.session,
            model_class=SvgVersion,
            predicate=SvgVersion.id == version_id,  # type: ignore[arg-type]
        )

        try:
            async with lock:
                version = lock.record
                assert version is not None

                # Validate ownership INSIDE the lock (atomic)
                if version.image_id != image_id:
                    raise VersionOwnershipError()

                # Verify status and update atomically using RecordLock helper
                await lock.verify_and_update_status(
                    expected=SvgProcessingStatus.ERROR,
                    new_status=SvgProcessingStatus.QUEUED,
                )

            await self.session.commit()

            logger.info("Prepared SVG version for retry", version_id=version_id)

            return version
        except RecordNotFoundError:
            raise SvgVersionNotFound()
        except UnexpectedStatusError:
            raise VersionNotInErrorState()

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
        """Get the next version number for an SVG version.

        Now a simple query since SvgVersion has image_id directly.
        """
        result = await self.session.execute(
            select(func.coalesce(func.max(SvgVersion.version), 0)).where(SvgVersion.image_id == image_id)
        )
        return (result.scalar() or 0) + 1

    @staticmethod
    async def get_incomplete_versions(session: AsyncSession) -> list[dict[str, int | str]]:
        """Get SVG versions stuck in intermediate states with context for recovery.

        Used by task recovery to find tasks that were interrupted.
        Excludes versions that already have file_ref (completed but status not updated).

        Returns:
            List of dicts with version_id, order_id, and image_id for each stuck version.
        """
        statement = (
            select(
                SvgVersion.id.label("version_id"),  # type: ignore[union-attr]
                Order.id.label("order_id"),  # type: ignore[attr-defined]
                Image.id.label("image_id"),  # type: ignore[union-attr]
            )
            .join(Image, SvgVersion.image_id == Image.id)  # type: ignore[arg-type]
            .join(LineItem, Image.line_item_id == LineItem.id)  # type: ignore[arg-type]
            .join(Order, LineItem.order_id == Order.id)  # type: ignore[arg-type]
            .where(
                SvgVersion.status.in_(SvgProcessingStatus.intermediate_states()),  # type: ignore[attr-defined]
                SvgVersion.file_ref.is_(None),  # type: ignore[union-attr]
            )
        )
        result = await session.execute(statement)
        return [
            {"version_id": row.version_id, "order_id": row.order_id, "image_id": row.image_id}
            for row in result.fetchall()
        ]
