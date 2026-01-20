"""Order ingestion background task."""

import asyncio

import dramatiq
import structlog

from app.models.enums import OrderStatus
from app.models.order import Order
from app.services.orders.shopify_sync_service import ShopifySyncService
from app.tasks.decorators import task_recover
from app.tasks.orders.image_download import download_order_images
from app.tasks.utils.task_db import task_db_session

logger = structlog.get_logger(__name__)


@task_recover(ShopifySyncService.get_incomplete_ingestions)
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def ingest_order(order_id: str) -> None:
    """Background task to ingest and process an order.

    This task:
    1. Sets status to PROCESSING
    2. Uses ShopifySyncService to fetch details and create line items/images
    3. Dispatches download_order_images task if there are images to download
    4. Mercure events are auto-published via TrackedAsyncSession

    This task is idempotent - running it multiple times for the same order
    will not corrupt data.
    """
    asyncio.run(_ingest_order_async(order_id))


async def _ingest_order_async(order_id: str) -> None:
    """Async implementation of order ingestion."""
    logger.info("Starting order ingestion", order_id=order_id)

    async with task_db_session() as session:
        order = await session.get(Order, order_id)
        if not order:
            logger.error("Order not found", order_id=order_id)
            return

        # Enable auto-tracking for Order.status changes
        session.track_changes(Order.status)  # type: ignore[arg-type]
        session.set_mercure_context(Order.id == order_id)  # type: ignore[arg-type]

        try:
            # Set status to PROCESSING (auto-published via TrackedAsyncSession)
            order.status = OrderStatus.PROCESSING
            await session.commit()

            # Use ShopifySyncService for the actual sync logic
            service = ShopifySyncService(session)
            result = await service.sync_single_order(order)

            if not result.success:
                logger.error("Order ingestion failed", order_id=order_id, error=result.error)
                order.status = OrderStatus.ERROR
                await session.commit()
                return

            # Dispatch image download task or mark complete
            if result.has_images_to_download:
                download_order_images.send(order_id)
                logger.info("Dispatched image download task", order_id=order_id)
            else:
                order.status = OrderStatus.READY_FOR_REVIEW
                await session.commit()

            logger.info("Order ingestion complete", order_id=order_id)

        except Exception as e:
            logger.error("Order ingestion failed", order_id=order_id, error=str(e))
            order.status = OrderStatus.ERROR
            await session.commit()
            raise
