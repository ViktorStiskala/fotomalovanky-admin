"""Image download service for order images."""

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Image, LineItem, Order
from app.services.storage.paths import OrderStoragePaths
from app.services.storage.storage_service import S3StorageService

logger = structlog.get_logger(__name__)


@dataclass
class DownloadResult:
    """Result of downloading images for an order."""

    total: int
    succeeded: int
    failed: int

    @property
    def all_succeeded(self) -> bool:
        """Check if all downloads succeeded."""
        return self.failed == 0

    @property
    def has_failures(self) -> bool:
        """Check if any downloads failed."""
        return self.failed > 0


class ImageDownloadService:
    """Service for downloading images from external URLs to S3."""

    def __init__(self, session: AsyncSession, storage: S3StorageService):
        """Initialize download service.

        Args:
            session: Database session for updating image records
            storage: S3 storage service for uploading files
        """
        self.session = session
        self.storage = storage

    def _get_extension_from_url(self, url: str) -> str:
        """Extract file extension from URL, defaulting to jpg."""
        if "." in url.split("/")[-1]:
            ext = url.split(".")[-1].lower().split("?")[0]
            if ext in ("jpg", "jpeg", "png", "gif", "webp"):
                return ext
        return "jpg"

    def _get_content_type(self, ext: str) -> str:
        """Get content type for file extension."""
        content_types = {
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "webp": "image/webp",
        }
        return content_types.get(ext, "application/octet-stream")

    async def download_single_image(
        self, image: Image, line_item: LineItem, paths: OrderStoragePaths
    ) -> bool:
        """Download a single image and upload to S3.

        Args:
            image: Image model instance to download
            line_item: LineItem containing this image
            paths: OrderStoragePaths instance for key generation

        Returns:
            True if download succeeded, False otherwise
        """
        assert image.id is not None, "Image ID cannot be None"

        if not image.original_url:
            logger.warning("Image has no original URL", image_id=image.id)
            return False

        try:
            ext = self._get_extension_from_url(image.original_url)
            content_type = self._get_content_type(ext)
            key = paths.original_image(line_item, image, ext)

            file_ref = await self.storage.upload_from_url(
                upload_to=key,
                source_url=image.original_url,
                content_type=content_type,
            )

            image.file_ref = file_ref
            image.uploaded_at = datetime.now(UTC)
            logger.info("Downloaded and uploaded image to S3", image_id=image.id, key=key)
            return True

        except Exception as e:
            logger.error(
                "Image download failed",
                image_id=image.id,
                url=image.original_url,
                error=str(e),
            )
            return False

    async def download_order_images(self, order: Order) -> DownloadResult:
        """Download all images for an order in parallel.

        Args:
            order: Order with line_items and images relationships loaded

        Returns:
            DownloadResult with success/failure counts
        """
        import asyncio

        assert order.id is not None, "Order ID cannot be None"
        paths = OrderStoragePaths(order)

        # Collect all images that need downloading (with their line items)
        images_to_download: list[tuple[Image, LineItem]] = [
            (image, line_item)
            for line_item in order.line_items
            for image in line_item.images
            if not image.file_ref
        ]

        if not images_to_download:
            logger.info("No images to download", order_id=order.id)
            return DownloadResult(total=0, succeeded=0, failed=0)

        logger.info(
            "Downloading images for order",
            order_id=order.id,
            image_count=len(images_to_download),
        )

        # Execute all downloads in parallel
        results = await asyncio.gather(
            *[
                self.download_single_image(img, line_item, paths)
                for img, line_item in images_to_download
            ],
            return_exceptions=True,
        )

        # Count successes and failures
        succeeded = sum(1 for r in results if r is True)
        failed = len(results) - succeeded

        logger.info(
            "Order image downloads complete",
            order_id=order.id,
            total=len(images_to_download),
            succeeded=succeeded,
            failed=failed,
        )

        return DownloadResult(
            total=len(images_to_download),
            succeeded=succeeded,
            failed=failed,
        )

    @staticmethod
    async def get_incomplete_downloads(session: AsyncSession) -> list[str]:
        """Get order IDs with incomplete image downloads.

        This is used by the task recovery decorator to find orders
        that need their downloads completed.

        Args:
            session: Database session

        Returns:
            List of order IDs (ULIDs) with pending downloads
        """
        from sqlmodel import select

        from app.models.enums import OrderStatus

        statement = select(Order.id).where(Order.status == OrderStatus.DOWNLOADING)
        result = await session.execute(statement)
        return list(result.scalars().all())
