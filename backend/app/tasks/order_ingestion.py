"""Order ingestion background task."""

import asyncio
import re
from typing import TYPE_CHECKING

import dramatiq
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import select

from app.config import settings

if TYPE_CHECKING:
    from app.services.shopify_client.graphql_client.get_order_details import (
        GetOrderDetailsOrderLineItemsEdgesNode,
    )

logger = structlog.get_logger(__name__)


def _create_task_session() -> async_sessionmaker[AsyncSession]:
    """Create a fresh engine and session maker for use in a single task.

    This is necessary because each asyncio.run() call creates a new event loop,
    and the database connections must be bound to the current event loop.
    """
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
    )
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


def extract_numeric_id(gid: str) -> int:
    """Extract numeric ID from Shopify GID format (e.g., 'gid://shopify/LineItem/12345')."""
    match = re.search(r"/(\d+)$", gid)
    if match:
        return int(match.group(1))
    raise ValueError(f"Could not extract numeric ID from GID: {gid}")


def extract_image_urls(attrs: dict[str, str]) -> list[tuple[int, str]]:
    """
    Extract image URLs and positions from custom attributes.

    Looks for keys like 'Fotka 1', 'Fotka 2', or 'Fotka (4)-1', 'Fotka (4)-2', etc.

    Returns:
        List of (position, url) tuples
    """
    images = []
    for key, value in attrs.items():
        if not value or not value.startswith("http"):
            continue

        # Match patterns like "Fotka 1", "Fotka (4)-1", "Fotka (4)-2"
        match = re.match(r"Fotka\s*(?:\(\d+\))?-?(\d+)", key)
        if match:
            position = int(match.group(1))
            images.append((position, value))

    return sorted(images, key=lambda x: x[0])


async def _process_line_item(
    session: AsyncSession,
    shopify_line_item: GetOrderDetailsOrderLineItemsEdgesNode,
    order_id: int,
) -> bool:
    """Process a single line item and its images.

    Returns:
        True if there are images that need downloading, False otherwise
    """
    from app.models.order import LineItem
    from app.services.shopify import parse_custom_attributes

    shopify_line_item_id = extract_numeric_id(shopify_line_item.id)
    attrs = parse_custom_attributes(shopify_line_item.custom_attributes)

    logger.debug(
        "Processing line item",
        title=shopify_line_item.title,
        shopify_line_item_id=shopify_line_item_id,
        quantity=shopify_line_item.quantity,
        custom_attrs=attrs,
    )

    # Check if LineItem already exists (idempotency)
    existing_stmt = select(LineItem).where(LineItem.shopify_line_item_id == shopify_line_item_id)
    existing_result = await session.execute(existing_stmt)
    line_item = existing_result.scalars().first()

    if not line_item:
        line_item = LineItem(
            order_id=order_id,
            shopify_line_item_id=shopify_line_item_id,
            title=shopify_line_item.title,
            quantity=shopify_line_item.quantity,
            dedication=attrs.get("Věnování"),
            layout=attrs.get("Rozvržení"),
        )
        session.add(line_item)
        await session.flush()
        logger.info("Created line item", line_item_id=line_item.id, shopify_line_item_id=shopify_line_item_id)

    assert line_item.id is not None, "LineItem ID cannot be None after flush"
    return await _process_images_for_line_item(session, line_item.id, attrs)


async def _process_images_for_line_item(
    session: AsyncSession,
    line_item_id: int,
    attrs: dict[str, str],
) -> bool:
    """Process images for a line item.

    Returns:
        True if there are images that need downloading, False otherwise
    """
    from app.models.order import Image

    has_images_to_download = False
    image_urls = extract_image_urls(attrs)

    for position, url in image_urls:
        img_stmt = select(Image).where(Image.line_item_id == line_item_id, Image.position == position)
        img_result = await session.execute(img_stmt)
        image = img_result.scalars().first()

        if not image:
            image = Image(line_item_id=line_item_id, position=position, original_url=url)
            session.add(image)
            await session.flush()
            has_images_to_download = True
            logger.info("Created image record", image_id=image.id, position=position, url=url[:50] + "...")
        elif not image.local_path:
            has_images_to_download = True

    return has_images_to_download


@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def ingest_order(order_id: int) -> None:
    """
    Background task to ingest and process an order.

    Steps:
    1. Fetch full order details from Shopify GraphQL API
    2. Create/update LineItem records
    3. Create Image records
    4. Dispatch download_order_images task for parallel image downloading
    5. Publish update event to Mercure

    This task is idempotent - running it multiple times for the same order
    will not corrupt data.
    """
    asyncio.run(_ingest_order_async(order_id))


async def _ingest_order_async(order_id: int) -> None:
    """Async implementation of order ingestion."""
    from app.models.enums import OrderStatus
    from app.models.order import Order
    from app.services.mercure import publish_order_update
    from app.services.shopify import get_order_details
    from app.tasks.image_download import download_order_images

    logger.info("Starting order ingestion", order_id=order_id)
    task_session_maker = _create_task_session()

    async with task_session_maker() as session:
        order = await session.get(Order, order_id)
        if not order:
            logger.error("Order not found", order_id=order_id)
            return

        assert order.id is not None, "Order ID cannot be None after database fetch"
        order_number = order.shopify_order_number.lstrip("#") if order.shopify_order_number else str(order.id)

        try:
            order.status = OrderStatus.PROCESSING
            await session.commit()
            await publish_order_update(order_number)

            shopify_order = await get_order_details(order.shopify_id)
            if not shopify_order:
                logger.error("Failed to fetch order from Shopify", order_id=order_id)
                order.status = OrderStatus.ERROR
                await session.commit()
                await publish_order_update(order_number)
                return

            logger.info(
                "Fetched Shopify order",
                order_id=order_id,
                shopify_name=shopify_order.name,
                fulfillment_status=shopify_order.display_fulfillment_status.value,
                line_item_count=len(shopify_order.line_items.edges),
            )

            # Update order metadata from Shopify
            if shopify_order.display_financial_status:
                order.payment_status = shopify_order.display_financial_status.value
            if shopify_order.shipping_line:
                order.shipping_method = shopify_order.shipping_line.title

            # Process all line items
            has_images_to_download = False
            for edge in shopify_order.line_items.edges:
                if await _process_line_item(session, edge.node, order_id):
                    has_images_to_download = True

            await session.commit()

            # Dispatch image download task or mark complete
            if has_images_to_download:
                download_order_images.send(order_id)
                logger.info("Dispatched image download task", order_id=order_id)
            else:
                order.status = OrderStatus.READY_FOR_REVIEW
                await session.commit()
                await publish_order_update(order_number)

            logger.info("Order ingestion complete", order_id=order_id)

        except Exception as e:
            logger.error("Order ingestion failed", order_id=order_id, error=str(e))
            order.status = OrderStatus.ERROR
            await session.commit()
            await publish_order_update(order_number)
            raise
