"""Shopify order fetching background task."""

import asyncio

import dramatiq
import structlog

from app.services.external.mercure import publish_order_list_update
from app.services.external.shopify import list_recent_orders
from app.services.orders.order_service import OrderService
from app.tasks.order_ingestion import ingest_order
from app.tasks.utils import task_db_session

logger = structlog.get_logger(__name__)


async def _fetch_orders_async(limit: int) -> dict[str, int]:
    """Async implementation of fetch_orders_from_shopify."""
    # Fetch from Shopify API
    shopify_orders = await list_recent_orders(limit=limit)
    if not shopify_orders:
        raise RuntimeError("Failed to fetch orders from Shopify")

    imported = 0
    updated = 0
    skipped = 0

    async with task_db_session() as session:
        service = OrderService(session)

        for edge in shopify_orders.edges:
            shopify_order = edge.node
            order, action = await service.create_or_update_from_shopify(shopify_order)

            if action == "imported":
                imported += 1
                assert order.id is not None
                ingest_order.send(order.id)
            elif action == "updated":
                updated += 1
                assert order.id is not None
                ingest_order.send(order.id)
            else:
                skipped += 1

    # Notify frontend about new orders if any were imported or updated
    if imported > 0 or updated > 0:
        await publish_order_list_update()

    logger.info(
        "Completed Shopify order fetch",
        imported=imported,
        updated=updated,
        skipped=skipped,
        total=len(shopify_orders.edges),
    )

    return {
        "imported": imported,
        "updated": updated,
        "skipped": skipped,
        "total": len(shopify_orders.edges),
    }


@dramatiq.actor(max_retries=3, min_backoff=5000, max_backoff=60000)
def fetch_orders_from_shopify(limit: int = 20) -> None:
    """
    Fetch recent orders from Shopify and import them.

    This task:
    1. Calls Shopify API to list recent orders
    2. Creates or updates orders in the database
    3. Dispatches ingest_order tasks for new/updated orders
    4. Publishes Mercure update when orders are imported/updated

    Args:
        limit: Maximum number of orders to fetch from Shopify
    """
    asyncio.run(_fetch_orders_async(limit))
