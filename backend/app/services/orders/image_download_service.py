"""Image download service for order images."""

from dataclasses import dataclass
from datetime import UTC, datetime

import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from tenacity import (
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from app.models.order import Image, Order
from app.services.storage.storage_service import StorageService

logger = structlog.get_logger(__name__)


def _is_retryable_error(exc: BaseException) -> bool:
    """Check if an exception is retryable.

    Retries on:
    - Network errors (httpx.RequestError)
    - Server errors (5xx status codes)
    - Rate limiting (429)

    Does NOT retry on:
    - Client errors (400, 404, etc.) - these indicate permanent failures
    """
    if isinstance(exc, httpx.RequestError):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        status = exc.response.status_code
        return status == 429 or status >= 500
    return False


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
    """Service for downloading images from external URLs."""

    def __init__(self, session: AsyncSession, storage: StorageService):
        """Initialize download service.

        Args:
            session: Database session for updating image records
            storage: Storage service for writing files
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

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        retry=retry_if_exception(_is_retryable_error),
        reraise=True,
    )
    async def _download_with_retry(
        self,
        url: str,
        shopify_id: int,
        line_item_id: int,
        position: int,
    ) -> str:
        """Download image with tenacity retry logic.

        Args:
            url: Source URL of the image
            shopify_id: Shopify order ID for path organization
            line_item_id: Line item ID for path organization
            position: Image position (1-4)

        Returns:
            Local file path where image was saved

        Raises:
            httpx.HTTPStatusError: On non-retryable HTTP errors
            httpx.RequestError: On network errors (after retries exhausted)
        """
        extension = self._get_extension_from_url(url)
        key = self.storage.get_original_image_key(shopify_id, line_item_id, position, extension)

        async with httpx.AsyncClient() as client:
            response = await client.get(url, timeout=60.0, follow_redirects=True)
            response.raise_for_status()

            file_path = await self.storage.write(key, response.content)

            logger.info(
                "Downloaded image",
                url=url,
                local_path=file_path,
                size=len(response.content),
            )
            return file_path

    async def download_single_image(self, image: Image, shopify_id: int) -> bool:
        """Download a single image and update its database record.

        Args:
            image: Image model instance to download
            shopify_id: Shopify order ID for path organization

        Returns:
            True if download succeeded, False otherwise
        """
        assert image.id is not None, "Image ID cannot be None"

        try:
            local_path = await self._download_with_retry(
                url=image.original_url,
                shopify_id=shopify_id,
                line_item_id=image.line_item_id,
                position=image.position,
            )
            image.local_path = local_path
            image.downloaded_at = datetime.now(UTC)
            logger.info("Downloaded image", image_id=image.id, local_path=local_path)
            return True

        except httpx.HTTPStatusError as e:
            logger.error(
                "Image download failed with HTTP error",
                image_id=image.id,
                url=image.original_url,
                status_code=e.response.status_code,
            )
            return False
        except httpx.RequestError as e:
            logger.error(
                "Image download failed after retries",
                image_id=image.id,
                url=image.original_url,
                error=str(e),
            )
            return False
        except Exception as e:
            logger.error(
                "Unexpected error downloading image",
                image_id=image.id,
                url=image.original_url,
                error=str(e),
            )
            return False

    async def download_order_images(self, order: Order) -> DownloadResult:
        """Download all images for an order in parallel.

        Uses per-image tenacity retries for transient failures.

        Args:
            order: Order with line_items and images relationships loaded

        Returns:
            DownloadResult with success/failure counts
        """
        import asyncio

        assert order.id is not None, "Order ID cannot be None"
        shopify_id = order.shopify_id

        # Collect all images that need downloading
        images_to_download = [
            image
            for line_item in order.line_items
            for image in line_item.images
            if not image.local_path
        ]

        if not images_to_download:
            logger.info("No images to download", shopify_id=shopify_id)
            return DownloadResult(total=0, succeeded=0, failed=0)

        logger.info(
            "Downloading images for order",
            shopify_id=shopify_id,
            image_count=len(images_to_download),
        )

        # Execute all downloads in parallel
        results = await asyncio.gather(
            *[self.download_single_image(img, shopify_id) for img in images_to_download],
            return_exceptions=True,
        )

        # Count successes and failures
        succeeded = sum(1 for r in results if r is True)
        failed = len(results) - succeeded

        logger.info(
            "Order image downloads complete",
            shopify_id=shopify_id,
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
    async def get_incomplete_downloads(session: AsyncSession) -> list[int]:
        """Get order IDs with incomplete image downloads.

        This is used by the task recovery decorator to find orders
        that need their downloads completed.

        Args:
            session: Database session

        Returns:
            List of order IDs with pending downloads
        """
        from sqlmodel import select

        from app.models.enums import OrderStatus

        statement = select(Order.id).where(Order.status == OrderStatus.DOWNLOADING)
        result = await session.execute(statement)
        return list(result.scalars().all())
