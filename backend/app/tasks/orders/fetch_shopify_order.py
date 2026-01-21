"""Shopify order fetching and ingestion background tasks.

This module contains tasks for:
- Batch fetching recent orders from Shopify
- Ingesting single orders (from webhook or manual sync)
"""

import asyncio

import dramatiq
import structlog

from app.models.enums import OrderStatus
from app.models.order import Order
from app.services.orders.order_service import OrderService
from app.services.orders.shopify_sync_service import ShopifySyncService
from app.tasks.orders.image_download import download_order_images
from app.tasks.utils.decorators import task_recover
from app.tasks.utils.task_db import task_db_session

logger = structlog.get_logger(__name__)


# ============================================================================
# Batch Fetch Task
# ============================================================================


@dramatiq.actor(max_retries=3, min_backoff=5000, max_backoff=60000)
def fetch_orders_from_shopify(limit: int = 20) -> None:
    """Fetch recent orders from Shopify and sync them directly.

    This task:
    1. Calls ShopifySyncService.sync_orders_batch() which handles full sync
    2. Dispatches download_order_images tasks for orders with images to download
    3. Mercure events are auto-published via @mercure_autotrack decorator

    Args:
        limit: Maximum number of orders to fetch from Shopify
    """
    asyncio.run(_fetch_orders_async(limit))


async def _fetch_orders_async(limit: int) -> None:
    """Async implementation of fetch_orders_from_shopify."""
    async with task_db_session() as session:
        # Defer batch events until all orders are processed
        # This batches multiple OrderUpdateEvents into a single ListUpdateEvent
        async with session.deferred_batch_events():
            service = ShopifySyncService(session)
            result, orders_needing_download = await service.sync_orders_batch(limit=limit)
        # Single batched ListUpdateEvent published here

        # Dispatch download tasks for orders with images
        for order_id in orders_needing_download:
            download_order_images.send(order_id)

    # ListUpdateEvent auto-published when Orders are created (via trigger_models)
    # OrderUpdateEvent auto-published when Order.status changes (via @mercure_autotrack)

    logger.info(
        "Completed Shopify order fetch",
        imported=result.imported,
        updated=result.updated,
        skipped=result.skipped,
        failed=result.failed,
        total=result.total,
    )


# ============================================================================
# Single Order Ingestion Task
# ============================================================================


@task_recover(ShopifySyncService.get_incomplete_ingestions)
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def ingest_order(order_id: str) -> None:
    """Background task to ingest and process a single order.

    This task:
    1. Sets status to PROCESSING
    2. Uses ShopifySyncService to fetch details and create line items/images
    3. Dispatches download_order_images task if there are images to download
    4. Mercure events are auto-published via @mercure_autotrack decorator

    This task is idempotent - running it multiple times for the same order
    will not corrupt data.
    """
    asyncio.run(_ingest_order_async(order_id))


async def _ingest_order_async(order_id: str) -> None:
    """Async implementation of order ingestion."""
    logger.info("Starting order ingestion", order_id=order_id)

    async with task_db_session() as session:
        order_service = OrderService(session)
        sync_service = ShopifySyncService(session)

        order = await session.get(Order, order_id)
        if not order:
            logger.error("Order not found", order_id=order_id)
            return

        try:
            # Update status via service (commits internally with lock)
            await order_service.update_status(order_id, OrderStatus.PROCESSING)

            # Use ShopifySyncService for the actual sync logic
            result = await sync_service.sync_single_order(order)

            if not result.success:
                logger.error("Order ingestion failed", order_id=order_id, error=result.error)
                await order_service.update_status(order_id, OrderStatus.ERROR)
                return

            # Dispatch image download task or mark complete
            if result.has_images_to_download:
                download_order_images.send(order_id)
                logger.info("Dispatched image download task", order_id=order_id)
            else:
                await order_service.update_status(order_id, OrderStatus.READY_FOR_REVIEW)

            logger.info("Order ingestion complete", order_id=order_id)

        except Exception as e:
            logger.error("Order ingestion failed", order_id=order_id, error=str(e))
            await order_service.update_status(order_id, OrderStatus.ERROR)
            raise
