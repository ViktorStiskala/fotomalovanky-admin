"""Order image service."""

import structlog
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.models.coloring import ColoringVersion, SvgVersion
from app.models.order import Image, LineItem, Order
from app.services.coloring.exceptions import (
    ColoringVersionNotFound,
    SvgVersionNotFound,
    VersionOwnershipError,
)
from app.services.orders.exceptions import ImageNotFound, ImageNotFoundInOrder, OrderNotFound
from app.utils.shopify_helpers import normalize_order_number

logger = structlog.get_logger(__name__)


class OrderImageService:
    """Service for image and version management."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_order_image(self, *, order_number: str, image_id: int) -> Image:
        """Get image with versions, verifying it belongs to the order."""
        normalized = normalize_order_number(order_number)

        # Verify order exists
        order_statement = select(Order).where(Order.shopify_order_number == normalized)
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
        """Select a coloring version as default for an image."""
        image = await self.get_image(image_id)

        coloring = await self.session.get(ColoringVersion, version_id)
        if not coloring:
            raise ColoringVersionNotFound()
        if coloring.image_id != image_id:
            raise VersionOwnershipError()

        image.selected_coloring_id = version_id
        await self.session.commit()

        logger.info("Selected coloring version", image_id=image_id, version_id=version_id)
        return image

    async def select_svg_version(self, image_id: int, version_id: int) -> Image:
        """Select an SVG version as default for an image."""
        image = await self.get_image(image_id)

        svg = await self.session.get(SvgVersion, version_id)
        if not svg:
            raise SvgVersionNotFound()

        coloring = await self.session.get(ColoringVersion, svg.coloring_version_id)
        if not coloring or coloring.image_id != image_id:
            raise VersionOwnershipError()

        image.selected_svg_id = version_id
        await self.session.commit()

        logger.info("Selected SVG version", image_id=image_id, version_id=version_id)
        return image

    async def list_coloring_versions(self, image_id: int) -> list[ColoringVersion]:
        """List all coloring versions for an image."""
        statement = (
            select(ColoringVersion).where(ColoringVersion.image_id == image_id).order_by(ColoringVersion.version.desc())  # type: ignore[attr-defined]
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

    async def list_svg_versions(self, image_id: int) -> list[SvgVersion]:
        """List all SVG versions for an image (across all colorings)."""
        # First get all coloring version IDs for this image
        coloring_ids_result = await self.session.execute(
            select(ColoringVersion.id).where(ColoringVersion.image_id == image_id)
        )
        coloring_ids = [row[0] for row in coloring_ids_result.fetchall()]

        if not coloring_ids:
            return []

        statement = (
            select(SvgVersion)
            .where(SvgVersion.coloring_version_id.in_(coloring_ids))  # type: ignore[attr-defined]
            .order_by(SvgVersion.version.desc())  # type: ignore[attr-defined]
        )
        result = await self.session.execute(statement)
        return list(result.scalars().all())

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
