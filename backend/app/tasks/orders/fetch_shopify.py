"""Shopify order fetching background task."""

import asyncio

import dramatiq
import structlog

from app.services.external.mercure import MercureService
from app.services.orders.shopify_sync_service import ShopifySyncService
from app.tasks.orders.order_ingestion import ingest_order
from app.tasks.utils import task_db_session

logger = structlog.get_logger(__name__)


@dramatiq.actor(max_retries=3, min_backoff=5000, max_backoff=60000)
def fetch_orders_from_shopify(limit: int = 20) -> None:
    """Fetch recent orders from Shopify and import them.

    This task:
    1. Calls ShopifySyncService to fetch and sync orders
    2. Dispatches ingest_order tasks for new/updated orders
    3. Publishes Mercure update when orders are imported/updated

    Args:
        limit: Maximum number of orders to fetch from Shopify
    """
    asyncio.run(_fetch_orders_async(limit))


async def _fetch_orders_async(limit: int) -> None:
    """Async implementation of fetch_orders_from_shopify."""
    mercure = MercureService()

    async with task_db_session() as session:
        service = ShopifySyncService(session)
        result, orders_to_ingest = await service.sync_orders_batch(limit=limit)

        # Dispatch ingest tasks for new/updated orders
        for order, _action in orders_to_ingest:
            assert order.id is not None
            ingest_order.send(order.id)

    # Notify frontend about new orders if any were imported or updated
    if result.has_changes:
        await mercure.publish_order_list_update()

    logger.info(
        "Completed Shopify order fetch",
        imported=result.imported,
        updated=result.updated,
        skipped=result.skipped,
        total=result.total,
    )
