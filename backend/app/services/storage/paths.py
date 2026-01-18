"""S3 storage path generation helpers.

This module provides domain-specific S3 key generation based on order structure.
"""

from typing import Final

from app.models.coloring import ColoringVersion, SvgVersion
from app.models.enums import VersionType
from app.models.order import Image, LineItem, Order

# Extension mapping for version types
_VERSION_EXTENSIONS: Final[dict[VersionType, str]] = {
    VersionType.COLORING: "png",
    VersionType.SVG: "svg",
}


class OrderStoragePaths:
    """Helper class to generate S3 object keys based on order structure.

    Uses private methods to build path segments, avoiding code duplication.
    All paths follow the pattern: orders/{order_id}/items/{position}/...
    """

    def __init__(self, order: Order) -> None:
        """Initialize with an order instance.

        Args:
            order: Order instance with id set
        """
        self.order = order

    @classmethod
    def from_order_id(cls, order_id: str) -> "OrderStoragePaths":
        """Create instance from just an order_id (ULID).

        Useful when you only have the order_id and don't need full order data.

        Args:
            order_id: Order ULID string

        Returns:
            OrderStoragePaths instance
        """
        # Create a minimal Order instance just for path generation
        order = Order.__new__(Order)
        order.id = order_id
        return cls(order)

    def _order_path(self) -> str:
        """Base path for order: orders/{order_id}"""
        return f"orders/{self.order.id}"

    def _line_item_path(self, line_item: LineItem) -> str:
        """Path to line item: orders/{order_id}/items/{position}"""
        return f"{self._order_path()}/items/{line_item.position}"

    def _image_filename(self, image: Image, ext: str) -> str:
        """Image filename with position: image_{position}.{ext}"""
        return f"image_{image.position}.{ext}"

    def _version_path(
        self,
        line_item: LineItem,
        image: Image,
        version_type: VersionType,
        version_num: int,
    ) -> str:
        """Path for versioned output.

        Pattern: orders/{order_id}/items/{pos}/{type}/v{ver}/image_{pos}.{ext}
        """
        ext = _VERSION_EXTENSIONS[version_type]
        return f"{self._line_item_path(line_item)}/{version_type}/v{version_num}/{self._image_filename(image, ext)}"

    def original_image(self, line_item: LineItem, image: Image, ext: str = "jpg") -> str:
        """Generate key for original image.

        Pattern: orders/{order_id}/items/{line_item_pos}/original/image_{image_pos}.{ext}

        Args:
            line_item: LineItem instance
            image: Image instance
            ext: File extension (default: jpg)

        Returns:
            S3 key for the original image
        """
        return f"{self._line_item_path(line_item)}/original/{self._image_filename(image, ext)}"

    def coloring_version(
        self,
        line_item: LineItem,
        image: Image,
        version: ColoringVersion,
    ) -> str:
        """Generate key for coloring version.

        Pattern: orders/{order_id}/items/{pos}/coloring/v{ver}/image_{pos}.png

        Args:
            line_item: LineItem instance
            image: Image instance
            version: ColoringVersion instance

        Returns:
            S3 key for the coloring version
        """
        return self._version_path(line_item, image, VersionType.COLORING, version.version)

    def svg_version(
        self,
        line_item: LineItem,
        image: Image,
        version: SvgVersion,
    ) -> str:
        """Generate key for SVG version.

        Pattern: orders/{order_id}/items/{pos}/svg/v{ver}/image_{pos}.svg

        Args:
            line_item: LineItem instance
            image: Image instance
            version: SvgVersion instance

        Returns:
            S3 key for the SVG version
        """
        return self._version_path(line_item, image, VersionType.SVG, version.version)
