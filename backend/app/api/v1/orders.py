"""Order API endpoints."""

from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import structlog
from dateutil.parser import parse as parse_datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.config import settings
from app.db import get_session
from app.models.enums import OrderStatus
from app.models.order import Image, LineItem, Order
from app.services.shopify import list_recent_orders
from app.tasks import ingest_order

logger = structlog.get_logger(__name__)

router = APIRouter()

# Timezone for API responses (from config)
API_TIMEZONE = ZoneInfo(settings.timezone)


def to_api_timezone(dt: datetime | None) -> datetime | None:
    """Convert a datetime to API timezone (from config)."""
    if dt is None:
        return None
    # Ensure datetime is timezone-aware (assume UTC if naive)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(API_TIMEZONE)


class OrderResponse(BaseModel):
    """Order response schema."""

    id: int
    shopify_id: int
    shopify_order_number: str
    customer_email: str | None
    customer_name: str | None
    status: OrderStatus
    item_count: int
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        """Serialize datetime to API timezone."""
        localized_dt = to_api_timezone(dt)
        assert localized_dt is not None
        return localized_dt.isoformat()


class ImageResponse(BaseModel):
    """Image response schema."""

    id: int
    position: int
    original_url: str
    local_path: str | None
    downloaded_at: datetime | None

    @field_serializer("downloaded_at")
    def serialize_downloaded_at(self, dt: datetime | None) -> str | None:
        """Serialize datetime to API timezone."""
        localized_dt = to_api_timezone(dt)
        return localized_dt.isoformat() if localized_dt else None


class LineItemResponse(BaseModel):
    """Line item response schema."""

    id: int
    title: str
    quantity: int
    dedication: str | None
    layout: str | None
    images: list[ImageResponse]


class OrderDetailResponse(BaseModel):
    """Detailed order response with line items and images."""

    id: int
    shopify_id: int
    shopify_order_number: str
    customer_email: str | None
    customer_name: str | None
    status: OrderStatus
    created_at: datetime
    line_items: list[LineItemResponse]

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        """Serialize datetime to API timezone."""
        localized_dt = to_api_timezone(dt)
        assert localized_dt is not None
        return localized_dt.isoformat()


class OrderListResponse(BaseModel):
    """Order list response schema."""

    orders: list[OrderResponse]
    total: int


@router.get("/orders", response_model=OrderListResponse)
async def list_orders(
    session: AsyncSession = Depends(get_session),
    skip: int = 0,
    limit: int = 50,
) -> OrderListResponse:
    """List all orders with pagination."""
    # Get orders with eager loading of line_items
    statement = (
        select(Order)
        .options(selectinload(Order.line_items))  # type: ignore[arg-type]
        .offset(skip)
        .limit(limit)
        .order_by(Order.created_at.desc())  # type: ignore[attr-defined]
    )
    result = await session.execute(statement)
    orders = result.scalars().all()

    # Get total count
    count_statement = select(Order)
    count_result = await session.execute(count_statement)
    total = len(count_result.scalars().all())

    return OrderListResponse(
        orders=[
            OrderResponse(
                id=order.id,  # type: ignore[arg-type]
                shopify_id=order.shopify_id,
                shopify_order_number=order.shopify_order_number,
                customer_email=order.customer_email,
                customer_name=order.customer_name,
                status=order.status,
                item_count=len(order.line_items),
                created_at=order.created_at,
            )
            for order in orders
        ],
        total=total,
    )


@router.get("/orders/{order_number}", response_model=OrderDetailResponse)
async def get_order(
    order_number: str,
    session: AsyncSession = Depends(get_session),
) -> OrderDetailResponse:
    """Get a single order with line items and images by Shopify order number."""
    # Support both "1270" and "#1270" formats
    normalized_number = f"#{order_number}" if not order_number.startswith("#") else order_number

    statement = (
        select(Order)
        .options(selectinload(Order.line_items).selectinload(LineItem.images))  # type: ignore[arg-type]
        .where(Order.shopify_order_number == normalized_number)
    )
    result = await session.execute(statement)
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    return OrderDetailResponse(
        id=order.id,  # type: ignore[arg-type]
        shopify_id=order.shopify_id,
        shopify_order_number=order.shopify_order_number,
        customer_email=order.customer_email,
        customer_name=order.customer_name,
        status=order.status,
        created_at=order.created_at,
        line_items=[
            LineItemResponse(
                id=li.id,  # type: ignore[arg-type]
                title=li.title,
                quantity=li.quantity,
                dedication=li.dedication,
                layout=li.layout,
                images=[
                    ImageResponse(
                        id=img.id,  # type: ignore[arg-type]
                        position=img.position,
                        original_url=img.original_url,
                        local_path=img.local_path,
                        downloaded_at=img.downloaded_at,
                    )
                    for img in sorted(li.images, key=lambda x: x.position)
                ],
            )
            for li in order.line_items
        ],
    )


@router.post("/orders/{order_number}/sync")
async def sync_order(
    order_number: str,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Manually trigger a sync/re-processing of an order."""
    # Support both "1270" and "#1270" formats
    normalized_number = f"#{order_number}" if not order_number.startswith("#") else order_number

    statement = select(Order).where(Order.shopify_order_number == normalized_number)
    result = await session.execute(statement)
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Reset status and enqueue task
    order.status = OrderStatus.PENDING
    await session.commit()

    # Type guard for order.id
    assert order.id is not None, "Order ID cannot be None"

    # Enqueue background task
    ingest_order.send(order.id)

    return {"status": "queued", "message": f"Order {order.shopify_order_number} queued for sync"}


class FetchFromShopifyResponse(BaseModel):
    """Response from fetch-from-shopify endpoint."""

    imported: int
    updated: int
    skipped: int
    total: int


def _order_needs_reprocessing(order: Order) -> bool:
    """Check if an existing order needs re-processing."""
    # Re-process if in error state
    if order.status == OrderStatus.ERROR:
        logger.info("Order in error state, re-queuing", order_id=order.id)
        return True

    # Re-process if no line items (incomplete ingestion)
    if len(order.line_items) == 0:
        logger.info("Order has no line items, re-queuing", order_id=order.id)
        return True

    # Re-process if any images are not downloaded
    for li in order.line_items:
        for img in li.images:
            if not img.local_path:
                logger.info("Order has undownloaded images, re-queuing", order_id=order.id, image_id=img.id)
                return True

    return False


@router.post("/orders/fetch-from-shopify", response_model=FetchFromShopifyResponse)
async def fetch_orders_from_shopify(
    session: AsyncSession = Depends(get_session),
    limit: int = 20,
) -> FetchFromShopifyResponse:
    """
    Manually fetch recent orders from Shopify and import/update them.

    - New orders are created and queued for processing
    - Existing orders with missing images or in error state are re-queued
    - Orders that are fully processed are skipped
    """
    # Fetch recent orders from Shopify
    shopify_orders = await list_recent_orders(limit=limit)
    if not shopify_orders:
        raise HTTPException(status_code=503, detail="Failed to fetch orders from Shopify")

    imported = 0
    updated = 0
    skipped = 0

    for edge in shopify_orders.edges:
        shopify_order = edge.node
        shopify_id = int(shopify_order.legacy_resource_id)

        # Check if order already exists
        existing_result = await session.execute(
            select(Order)
            .options(selectinload(Order.line_items).selectinload(LineItem.images))  # type: ignore[arg-type]
            .where(Order.shopify_id == shopify_id)
        )
        existing_order = existing_result.scalars().first()

        if existing_order:
            if _order_needs_reprocessing(existing_order) and existing_order.id is not None:
                existing_order.status = OrderStatus.PENDING
                await session.flush()
                ingest_order.send(existing_order.id)
                updated += 1
            else:
                skipped += 1
                logger.debug("Order already processed, skipping", shopify_id=shopify_id)
            continue

        # Build customer name from customer object
        customer_name = None
        if shopify_order.customer:
            first = shopify_order.customer.first_name or ""
            last = shopify_order.customer.last_name or ""
            customer_name = f"{first} {last}".strip() or None

        # Parse Shopify created_at timestamp and convert to UTC for storage
        shopify_created_at = parse_datetime(str(shopify_order.created_at))
        if shopify_created_at.tzinfo is not None:
            shopify_created_at = shopify_created_at.astimezone(UTC)

        # Create new order
        order = Order(
            shopify_id=shopify_id,
            shopify_order_number=shopify_order.name,
            customer_email=shopify_order.email,
            customer_name=customer_name,
            status=OrderStatus.PENDING,
            created_at=shopify_created_at,
        )
        session.add(order)
        await session.flush()  # Get the order ID

        # Type guard: order.id should be set after flush
        assert order.id is not None, "Order ID cannot be None after flush"

        # Enqueue ingestion task
        ingest_order.send(order.id)
        imported += 1

        logger.info(
            "Imported order from Shopify",
            order_id=order.id,
            shopify_id=shopify_id,
            shopify_name=shopify_order.name,
        )

    await session.commit()

    return FetchFromShopifyResponse(
        imported=imported,
        updated=updated,
        skipped=skipped,
        total=len(shopify_orders.edges),
    )


@router.get("/images/{image_id}")
async def get_image(
    image_id: int,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Serve a downloaded image file."""
    image = await session.get(Image, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if not image.local_path:
        raise HTTPException(status_code=404, detail="Image not downloaded yet")

    file_path = Path(image.local_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Image file not found")

    # Determine media type from extension
    extension = file_path.suffix.lower()
    media_types = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".gif": "image/gif",
        ".webp": "image/webp",
    }
    media_type = media_types.get(extension, "image/jpeg")

    return FileResponse(file_path, media_type=media_type)
