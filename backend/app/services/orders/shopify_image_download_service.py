"""Shopify image download service for order images."""

from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.order import Image, LineItem, Order
from app.services.download.download_service import DownloadService
from app.services.storage.paths import OrderStoragePaths
from app.services.storage.storage_service import S3StorageService

logger = structlog.get_logger(__name__)

# Referer header for Shopify image downloads
SHOPIFY_REFERER = "https://admin.shopify.com/"


@dataclass
class DownloadResult:
    """Result of downloading images for an order."""

    total: int
    succeeded: int
    failed: int

    @property
    def all_succeeded(self) -> bool:
        return self.failed == 0

    @property
    def has_failures(self) -> bool:
        return self.failed > 0


class ShopifyImageDownloadService:
    """Service for downloading Shopify order images to S3."""

    def __init__(
        self,
        session: AsyncSession,
        storage: S3StorageService,
        download_service: DownloadService,
    ):
        self.session = session
        self.storage = storage
        self.download_service = download_service

    def _get_extension_from_url(self, url: str) -> str:
        """Extract file extension from URL, defaulting to jpg."""
        if "." in url.split("/")[-1]:
            ext = url.split(".")[-1].lower().split("?")[0]
            if ext in ("jpg", "jpeg", "png", "gif", "webp", "heic"):
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
            "heic": "image/heic",
        }
        return content_types.get(ext, "application/octet-stream")

    async def download_single_image(
        self, image: Image, line_item: LineItem, paths: OrderStoragePaths
    ) -> bool:
        """Download a single image and upload to S3."""
        assert image.id is not None, "Image ID cannot be None"

        if not image.original_url:
            logger.warning("Image has no original URL", image_id=image.id)
            return False

        try:
            ext = self._get_extension_from_url(image.original_url)
            content_type = self._get_content_type(ext)
            key = paths.original_image(line_item, image, ext)

            # Download with Shopify Referer header and proxy fallback
            data = await self.download_service.download(
                url=image.original_url,
                extra_headers={"Referer": SHOPIFY_REFERER},
                proxy_fallback=True,
            )

            # Upload to S3
            file_ref = await self.storage.upload(
                upload_to=key,
                data=data,
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
        """Download all images for an order in parallel."""
        import asyncio

        assert order.id is not None, "Order ID cannot be None"
        paths = OrderStoragePaths(order)

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

        results = await asyncio.gather(
            *[
                self.download_single_image(img, line_item, paths)
                for img, line_item in images_to_download
            ],
            return_exceptions=True,
        )

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
        """Get order IDs with incomplete image downloads."""
        from sqlmodel import select

        from app.models.enums import OrderStatus

        statement = select(Order.id).where(Order.status == OrderStatus.DOWNLOADING)
        result = await session.execute(statement)
        return list(result.scalars().all())
