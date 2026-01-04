"""Order ingestion background task."""

import asyncio
import re
from datetime import datetime

import dramatiq
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlmodel import select

from app.config import settings

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


@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def ingest_order(order_id: int) -> None:
    """
    Background task to ingest and process an order.

    Steps:
    1. Fetch full order details from Shopify GraphQL API
    2. Create/update LineItem records
    3. Download high-res customer images
    4. Update order status in database
    5. Publish update event to Mercure

    This task is idempotent - running it multiple times for the same order
    will not corrupt data.
    """
    asyncio.run(_ingest_order_async(order_id))


async def _ingest_order_async(order_id: int) -> None:
    """Async implementation of order ingestion."""
    from app.models.enums import OrderStatus
    from app.models.order import Image, LineItem, Order
    from app.services.image_proc import download_image
    from app.services.mercure import publish_order_update
    from app.services.shopify import get_order_details, parse_custom_attributes

    logger.info("Starting order ingestion", order_id=order_id)

    # Create fresh session maker for this task's event loop
    task_session_maker = _create_task_session()

    async with task_session_maker() as session:
        # Get order from database
        order = await session.get(Order, order_id)
        if not order:
            logger.error("Order not found", order_id=order_id)
            return

        # Type guard: order.id should always be set after fetching from DB
        assert order.id is not None, "Order ID cannot be None after database fetch"

        try:
            # Update status to downloading
            order.status = OrderStatus.DOWNLOADING
            await session.commit()
            await publish_order_update(order.id)

            # Fetch full details from Shopify using typed client
            shopify_order = await get_order_details(order.shopify_id)
            if not shopify_order:
                logger.error("Failed to fetch order from Shopify", order_id=order_id)
                order.status = OrderStatus.ERROR
                await session.commit()
                await publish_order_update(order.id)
                return

            # Log typed order data
            logger.info(
                "Fetched Shopify order",
                order_id=order_id,
                shopify_name=shopify_order.name,
                fulfillment_status=shopify_order.display_fulfillment_status.value,
                line_item_count=len(shopify_order.line_items.edges),
            )

            # Process line items
            for edge in shopify_order.line_items.edges:
                shopify_line_item = edge.node
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
                    # Create new LineItem
                    line_item = LineItem(
                        order_id=order_id,
                        shopify_line_item_id=shopify_line_item_id,
                        title=shopify_line_item.title,
                        quantity=shopify_line_item.quantity,
                        dedication=attrs.get("Věnování"),
                        layout=attrs.get("Rozvržení"),
                    )
                    session.add(line_item)
                    await session.flush()  # Get the ID

                    logger.info(
                        "Created line item",
                        line_item_id=line_item.id,
                        shopify_line_item_id=shopify_line_item_id,
                    )

                # Type guard: line_item.id should be set after flush or from DB
                assert line_item.id is not None, "LineItem ID cannot be None after flush"
                line_item_db_id: int = line_item.id

                # Extract and process images
                image_urls = extract_image_urls(attrs)
                for position, url in image_urls:
                    # Check if Image already exists (idempotency)
                    img_stmt = select(Image).where(
                        Image.line_item_id == line_item_db_id,
                        Image.position == position,
                    )
                    img_result = await session.execute(img_stmt)
                    image = img_result.scalars().first()

                    if not image:
                        # Create new Image record
                        image = Image(
                            line_item_id=line_item_db_id,
                            position=position,
                            original_url=url,
                        )
                        session.add(image)
                        await session.flush()

                        logger.info(
                            "Created image record",
                            image_id=image.id,
                            position=position,
                            url=url[:50] + "...",
                        )

                    # Download image if not already downloaded
                    if not image.local_path:
                        local_path = await download_image(
                            url=url,
                            order_id=order_id,
                            line_item_id=line_item_db_id,
                            position=position,
                        )
                        if local_path:
                            image.local_path = local_path
                            image.downloaded_at = datetime.utcnow()
                            logger.info(
                                "Downloaded image",
                                image_id=image.id,
                                local_path=local_path,
                            )
                        else:
                            logger.warning(
                                "Failed to download image",
                                image_id=image.id,
                                url=url,
                            )

            await session.commit()

            # Update status to processing
            order.status = OrderStatus.PROCESSING
            await session.commit()
            await publish_order_update(order.id)

            # Update status to ready
            order.status = OrderStatus.READY_FOR_REVIEW
            await session.commit()
            await publish_order_update(order.id)

            logger.info("Order ingestion complete", order_id=order_id)

        except Exception as e:
            logger.error("Order ingestion failed", order_id=order_id, error=str(e))
            order.status = OrderStatus.ERROR
            await session.commit()
            await publish_order_update(order.id)
            raise
