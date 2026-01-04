"""Order API endpoints."""

from datetime import datetime
from pathlib import Path

import structlog
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.db import get_session
from app.models.enums import OrderStatus
from app.models.order import Image, LineItem, Order
from app.services.shopify import list_recent_orders
from app.tasks import ingest_order

logger = structlog.get_logger(__name__)

router = APIRouter()


class OrderResponse(BaseModel):
    """Order response schema."""

    id: int
    shopify_id: int
    shopify_order_number: str
    customer_email: str | None
    customer_name: str | None
    status: OrderStatus
    item_count: int


class ImageResponse(BaseModel):
    """Image response schema."""

    id: int
    position: int
    original_url: str
    local_path: str | None
    downloaded_at: datetime | None


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
            )
            for order in orders
        ],
        total=total,
    )


@router.get("/orders/{order_id}", response_model=OrderDetailResponse)
async def get_order(
    order_id: int,
    session: AsyncSession = Depends(get_session),
) -> OrderDetailResponse:
    """Get a single order with line items and images."""
    statement = (
        select(Order)
        .options(selectinload(Order.line_items).selectinload(LineItem.images))  # type: ignore[arg-type]
        .where(Order.id == order_id)
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


@router.post("/orders/{order_id}/sync")
async def sync_order(
    order_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Manually trigger a sync/re-processing of an order."""
    order = await session.get(Order, order_id)
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Reset status and enqueue task
    order.status = OrderStatus.PENDING
    await session.commit()

    # Enqueue background task
    ingest_order.send(order_id)

    return {"status": "queued", "message": f"Order {order_id} queued for sync"}


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

        # Create new order
        order = Order(
            shopify_id=shopify_id,
            shopify_order_number=shopify_order.name,
            customer_email=shopify_order.email,
            customer_name=customer_name,
            status=OrderStatus.PENDING,
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
