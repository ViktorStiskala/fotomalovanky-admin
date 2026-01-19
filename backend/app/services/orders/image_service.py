"""Order image service."""

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.models.coloring import ColoringVersion, SvgVersion
from app.models.enums import ColoringProcessingStatus, SvgProcessingStatus
from app.models.order import Image, LineItem, Order
from app.services.coloring.exceptions import (
    ColoringVersionNotFound,
    SvgVersionNotFound,
    VersionNotCompleted,
    VersionOwnershipError,
)
from app.services.orders.exceptions import ImageNotFound, ImageNotFoundInOrder, OrderNotFound

logger = structlog.get_logger(__name__)


class OrderImageService:
    """Service for image and version management."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_order_image(self, *, order_id: str, image_id: int) -> Image:
        """Get image with versions, verifying it belongs to the order."""
        # Verify order exists
        order_statement = select(Order).where(Order.id == order_id)
        order_result = await self.session.execute(order_statement)
        order = order_result.scalars().first()
        if not order:
            raise OrderNotFound()

        # Get image with all versions
        image = await self._get_image_with_versions(image_id)
        if not image:
            raise ImageNotFound()

        # Verify image belongs to the order
        line_item = await self.session.get(LineItem, image.line_item_id)
        if not line_item or line_item.order_id != order.id:
            raise ImageNotFoundInOrder()

        return image

    async def get_image(self, image_id: int) -> Image:
        """Get image with all versions and related order info loaded."""
        statement = (
            select(Image)
            .options(
                selectinload(Image.coloring_versions).selectinload(ColoringVersion.svg_versions),  # type: ignore[arg-type]
                selectinload(Image.line_item).selectinload(LineItem.order),  # type: ignore[arg-type]
            )
            .where(Image.id == image_id)
        )
        result = await self.session.execute(statement)
        image = result.scalars().first()
        if not image:
            raise ImageNotFound()
        return image

    async def select_coloring_version(self, image_id: int, version_id: int) -> Image:
        """Select a coloring version as default for an image.

        Only completed versions can be selected.
        """
        image = await self.get_image(image_id)

        coloring = await self.session.get(ColoringVersion, version_id)
        if not coloring:
            raise ColoringVersionNotFound()
        if coloring.image_id != image_id:
            raise VersionOwnershipError()
        if coloring.status != ColoringProcessingStatus.COMPLETED:
            raise VersionNotCompleted()

        image.selected_coloring_id = version_id
        await self.session.commit()

        logger.info("Selected coloring version", image_id=image_id, version_id=version_id)
        return image

    async def select_svg_version(self, image_id: int, version_id: int) -> Image:
        """Select an SVG version as default for an image.

        Only completed versions can be selected.
        """
        image = await self.get_image(image_id)

        svg = await self.session.get(SvgVersion, version_id)
        if not svg:
            raise SvgVersionNotFound()

        # SvgVersion now has direct image_id reference
        if svg.image_id != image_id:
            raise VersionOwnershipError()
        if svg.status != SvgProcessingStatus.COMPLETED:
            raise VersionNotCompleted()

        image.selected_svg_id = version_id
        await self.session.commit()

        logger.info("Selected SVG version", image_id=image_id, version_id=version_id)
        return image

    async def _get_image_with_versions(self, image_id: int) -> Image | None:
        """Get image with coloring and SVG versions loaded."""
        statement = (
            select(Image)
            .options(
                selectinload(Image.coloring_versions).selectinload(ColoringVersion.svg_versions)  # type: ignore[arg-type]
            )
            .where(Image.id == image_id)
        )
        result = await self.session.execute(statement)
        return result.scalars().first()

    async def get_next_coloring_version(self, image_id: int) -> int:
        """Get the next version number for a coloring version."""
        result = await self.session.execute(
            select(func.coalesce(func.max(ColoringVersion.version), 0)).where(ColoringVersion.image_id == image_id)
        )
        max_version = result.scalar() or 0
        return max_version + 1

    async def get_next_svg_version(self, image_id: int) -> int:
        """Get the next version number for an SVG version.

        Now a simple query since SvgVersion has image_id directly.
        """
        result = await self.session.execute(
            select(func.coalesce(func.max(SvgVersion.version), 0)).where(SvgVersion.image_id == image_id)
        )
        return (result.scalar() or 0) + 1
