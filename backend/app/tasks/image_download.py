"""Image download background task."""

import asyncio
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from typing import TYPE_CHECKING

import dramatiq
import httpx
import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlmodel import select
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.config import settings

if TYPE_CHECKING:
    from app.models.order import Image, Order

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def task_db_session() -> AsyncGenerator[AsyncSession]:
    """Context manager that provides a database session for background tasks.

    Creates a fresh engine bound to the current event loop, yields a session,
    and ensures proper cleanup of both the session and engine connection pool.

    This is necessary because each asyncio.run() call creates a new event loop,
    and the database connections must be bound to the current event loop.
    """
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
        pool_size=2,
        max_overflow=3,
        pool_pre_ping=True,
    )
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_maker() as session:
        try:
            yield session
        finally:
            pass  # Session cleanup handled by context manager
    # Dispose engine to release all connections back to PostgreSQL
    await engine.dispose()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=30),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.RequestError)),
    reraise=True,
)
async def _download_single_image_with_retry(
    url: str,
    order_id: int,
    line_item_id: int,
    position: int,
) -> str | None:
    """Download a single image with retry logic.

    Uses tenacity for per-image retries with exponential backoff.

    Args:
        url: Source URL of the image
        order_id: Order ID for path organization
        line_item_id: Line item ID for path organization
        position: Image position (1-4)

    Returns:
        Local file path if successful, None otherwise
    """
    from app.services.image_proc import download_image

    return await download_image(
        url=url,
        order_id=order_id,
        line_item_id=line_item_id,
        position=position,
    )


async def _download_and_update_image(image: Image, order_id: int) -> bool:
    """Download a single image and update its record.

    Args:
        image: Image model instance to download
        order_id: Order ID for path organization

    Returns:
        True if download succeeded, False otherwise
    """
    assert image.id is not None, "Image ID cannot be None"
    try:
        local_path = await _download_single_image_with_retry(
            url=image.original_url,
            order_id=order_id,
            line_item_id=image.line_item_id,
            position=image.position,
        )
        if local_path:
            image.local_path = local_path
            image.downloaded_at = datetime.now(UTC)
            logger.info("Downloaded image", image_id=image.id, local_path=local_path)
            return True
        logger.warning(
            "Failed to download image (no path returned)",
            image_id=image.id,
            url=image.original_url,
        )
        return False
    except Exception as e:
        logger.error(
            "Failed to download image after retries",
            image_id=image.id,
            url=image.original_url,
            error=str(e),
        )
        return False


@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def download_order_images(order_id: int) -> None:
    """Download all images for an order in parallel.

    This task:
    1. Sets order status to DOWNLOADING
    2. Queries all Image records that need downloading
    3. Downloads all images in parallel using asyncio.gather
    4. Updates Image records with local paths
    5. Sets order status to READY_FOR_REVIEW (or ERROR if any failed)
    6. Publishes Mercure updates at each stage

    The task has two layers of retry:
    - Per-image retries via tenacity (handles transient network failures)
    - Task-level retries via Dramatiq (handles catastrophic failures)
    """
    asyncio.run(_download_order_images_async(order_id))


async def _download_order_images_async(order_id: int) -> None:
    """Async implementation of image downloading."""
    from app.models.enums import OrderStatus
    from app.models.order import LineItem, Order
    from app.services.mercure import publish_order_update

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

        assert order.id is not None, "Order ID cannot be None after database fetch"
        order_number = order.clean_order_number if order.shopify_order_number else str(order.id)

        try:
            await _process_image_downloads(session, order, order_number, order_id)
        except Exception as e:
            logger.error("Image download task failed", order_id=order_id, error=str(e))
            order.status = OrderStatus.ERROR
            await session.commit()
            await publish_order_update(order_number)
            raise


async def _process_image_downloads(
    session: AsyncSession,
    order: Order,
    order_number: str,
    order_id: int,
) -> None:
    """Process all image downloads for an order."""
    from app.models.enums import OrderStatus
    from app.services.mercure import publish_order_update

    # Update status to DOWNLOADING
    order.status = OrderStatus.DOWNLOADING
    await session.commit()
    await publish_order_update(order_number)

    # Collect all images that need downloading
    images_to_download = [image for line_item in order.line_items for image in line_item.images if not image.local_path]

    if not images_to_download:
        logger.info("No images to download", order_id=order_id)
        order.status = OrderStatus.READY_FOR_REVIEW
        await session.commit()
        await publish_order_update(order_number)
        return

    logger.info("Downloading images", order_id=order_id, image_count=len(images_to_download))

    # Execute all downloads in parallel
    results = await asyncio.gather(
        *[_download_and_update_image(img, order_id) for img in images_to_download],
        return_exceptions=True,
    )

    # Commit image updates
    await session.commit()

    # Update order status based on results
    any_failed = any(result is not True for result in results)
    order.status = OrderStatus.ERROR if any_failed else OrderStatus.READY_FOR_REVIEW

    await session.commit()
    await publish_order_update(order_number)

    logger.info("Image download task complete", order_id=order_id, status=order.status.value)
