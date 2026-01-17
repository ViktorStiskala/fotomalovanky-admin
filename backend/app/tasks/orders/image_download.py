"""Image download background task."""

import asyncio

import dramatiq
import structlog
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.models.enums import OrderStatus
from app.models.order import LineItem, Order
from app.services.external.mercure import MercureService
from app.services.orders.image_download_service import ImageDownloadService
from app.services.storage.storage_service import S3StorageService
from app.tasks.decorators import task_recover
from app.tasks.utils import task_db_session

logger = structlog.get_logger(__name__)


@task_recover(ImageDownloadService.get_incomplete_downloads)
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def download_order_images(order_id: str) -> None:
    """Download all images for an order in parallel.

    This task:
    1. Sets order status to DOWNLOADING
    2. Uses ImageDownloadService to download all images
    3. Sets order status to READY_FOR_REVIEW (or ERROR if any failed)
    4. Publishes Mercure updates at each stage

    The task has two layers of retry:
    - Per-image retries via tenacity in ImageDownloadService (handles transient failures)
    - Task-level retries via Dramatiq (handles catastrophic failures)
    """
    asyncio.run(_download_order_images_async(order_id))


async def _download_order_images_async(order_id: str) -> None:
    """Async implementation of image downloading."""
    mercure = MercureService()
    storage = S3StorageService()

    logger.info("Starting image download task", order_id=order_id)

    async with task_db_session() as session:
        # Get order from database with line items and images
        statement = (
            select(Order)
            .options(selectinload(Order.line_items).selectinload(LineItem.images))  # type: ignore[arg-type]
            .where(Order.id == order_id)
        )
        result = await session.execute(statement)
        order = result.scalars().first()

        if not order:
            logger.error("Order not found", order_id=order_id)
            return

        logger.info("Downloading images for order", order_id=order_id, order_number=order.order_number)

        try:
            # Update status to DOWNLOADING
            order.status = OrderStatus.DOWNLOADING
            await session.commit()
            await mercure.publish_order_update(order_id)

            # Use ImageDownloadService for downloads
            download_service = ImageDownloadService(session, storage)
            download_result = await download_service.download_order_images(order)

            # Commit image updates from service
            await session.commit()

            # Update order status based on results
            if download_result.total == 0:
                order.status = OrderStatus.READY_FOR_REVIEW
            elif download_result.has_failures:
                order.status = OrderStatus.ERROR
            else:
                order.status = OrderStatus.READY_FOR_REVIEW

            await session.commit()
            await mercure.publish_order_update(order_id)

            logger.info(
                "Image download task complete",
                order_id=order_id,
                status=order.status.value,
                total=download_result.total,
                succeeded=download_result.succeeded,
                failed=download_result.failed,
            )

        except Exception as e:
            logger.error("Image download task failed", order_id=order_id, error=str(e))
            order.status = OrderStatus.ERROR
            await session.commit()
            await mercure.publish_order_update(order_id)
            raise
