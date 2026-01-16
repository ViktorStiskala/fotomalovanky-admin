"""Order API endpoints."""

from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING

import structlog
from dateutil.parser import parse as parse_datetime
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, field_serializer
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.db import get_session
from app.models.coloring import ColoringVersion, SvgVersion
from app.models.enums import ImageProcessingStatus, OrderStatus
from app.models.order import Image, LineItem, Order
from app.services.mercure import publish_order_list_update
from app.services.shopify import list_recent_orders
from app.tasks import generate_coloring, ingest_order, vectorize_image
from app.utils import build_customer_name, normalize_order_number, to_api_timezone

if TYPE_CHECKING:
    from app.services.shopify_client.graphql_client.list_recent_orders import (
        ListRecentOrdersOrdersEdgesNode,
    )

logger = structlog.get_logger(__name__)

router = APIRouter()


class OrderResponse(BaseModel):
    """Order response schema."""

    id: int
    shopify_id: int
    shopify_order_number: str
    customer_email: str | None
    customer_name: str | None
    payment_status: str | None
    status: OrderStatus
    item_count: int
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        """Serialize datetime to API timezone."""
        localized_dt = to_api_timezone(dt)
        assert localized_dt is not None
        return localized_dt.isoformat()


class SvgVersionResponse(BaseModel):
    """SVG version response schema."""

    id: int
    version: int
    file_path: str | None
    status: ImageProcessingStatus
    coloring_version_id: int
    shape_stacking: str
    group_by: str
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        """Serialize datetime to API timezone."""
        localized_dt = to_api_timezone(dt)
        assert localized_dt is not None
        return localized_dt.isoformat()


class ColoringVersionResponse(BaseModel):
    """Coloring version response schema."""

    id: int
    version: int
    file_path: str | None
    status: ImageProcessingStatus
    megapixels: float
    steps: int
    created_at: datetime
    svg_versions: list[SvgVersionResponse] = []

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
    selected_coloring_id: int | None
    selected_svg_id: int | None
    coloring_versions: list[ColoringVersionResponse]

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
    payment_status: str | None
    shipping_method: str | None
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
    from sqlalchemy import func

    # Get orders with eager loading of line_items
    orders_statement = (
        select(Order)
        .options(selectinload(Order.line_items))  # type: ignore[arg-type]
        .offset(skip)
        .limit(limit)
        .order_by(Order.created_at.desc())  # type: ignore[attr-defined]
    )
    orders_result = await session.execute(orders_statement)
    orders = orders_result.scalars().all()

    # Get total count (efficient - uses SQL COUNT)
    count_statement = select(func.count()).select_from(Order)
    count_result = await session.execute(count_statement)
    total = count_result.scalar() or 0

    return OrderListResponse(
        orders=[
            OrderResponse(
                id=order.id,  # type: ignore[arg-type]
                shopify_id=order.shopify_id,
                shopify_order_number=order.shopify_order_number,
                customer_email=order.customer_email,
                customer_name=order.customer_name,
                payment_status=order.payment_status,
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
    normalized_number = normalize_order_number(order_number)

    statement = (
        select(Order)
        .options(
            selectinload(Order.line_items)  # type: ignore[arg-type]
            .selectinload(LineItem.images)  # type: ignore[arg-type]
            .selectinload(Image.coloring_versions)  # type: ignore[arg-type]
            .selectinload(ColoringVersion.svg_versions)  # type: ignore[arg-type]
        )
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
        payment_status=order.payment_status,
        shipping_method=order.shipping_method,
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
                        selected_coloring_id=img.selected_coloring_id,
                        selected_svg_id=img.selected_svg_id,
                        coloring_versions=[
                            ColoringVersionResponse(
                                id=cv.id,  # type: ignore[arg-type]
                                version=cv.version,
                                file_path=cv.file_path,
                                status=cv.status,
                                megapixels=cv.megapixels,
                                steps=cv.steps,
                                created_at=cv.created_at,
                                svg_versions=[
                                    SvgVersionResponse(
                                        id=sv.id,  # type: ignore[arg-type]
                                        version=sv.version,
                                        file_path=sv.file_path,
                                        status=sv.status,
                                        coloring_version_id=sv.coloring_version_id,
                                        shape_stacking=sv.shape_stacking,
                                        group_by=sv.group_by,
                                        created_at=sv.created_at,
                                    )
                                    for sv in sorted(cv.svg_versions, key=lambda x: x.version)
                                ],
                            )
                            for cv in sorted(img.coloring_versions, key=lambda x: x.version)
                        ],
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
    normalized_number = normalize_order_number(order_number)

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


def _update_order_from_shopify(
    order: Order,
    shopify_order: ListRecentOrdersOrdersEdgesNode,
) -> None:
    """Update order with latest data from Shopify (payment status, shipping method, etc.)."""
    # Update payment status
    if shopify_order.display_financial_status:
        order.payment_status = shopify_order.display_financial_status.value

    # Update shipping method
    if shopify_order.shipping_line:
        order.shipping_method = shopify_order.shipping_line.title

    # Update customer info if changed
    if shopify_order.customer:
        customer_name = build_customer_name(
            shopify_order.customer.first_name,
            shopify_order.customer.last_name,
        )
        if customer_name:
            order.customer_name = customer_name

    if shopify_order.email:
        order.customer_email = shopify_order.email


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
            # Always update basic order info from Shopify (payment status, shipping method, etc.)
            _update_order_from_shopify(existing_order, shopify_order)

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
            customer_name = build_customer_name(
                shopify_order.customer.first_name,
                shopify_order.customer.last_name,
            )

        # Extract payment status (convert enum to string if present)
        payment_status = None
        if shopify_order.display_financial_status:
            payment_status = shopify_order.display_financial_status.value

        # Extract shipping method
        shipping_method = shopify_order.shipping_line.title if shopify_order.shipping_line else None

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
            payment_status=payment_status,
            shipping_method=shipping_method,
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

    # Notify frontend about new/updated orders via Mercure
    if imported > 0 or updated > 0:
        await publish_order_list_update()

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


# =============================================================================
# Coloring Generation Endpoints
# =============================================================================


class GenerateColoringRequest(BaseModel):
    """Request body for coloring generation."""

    megapixels: float = 1.0
    steps: int = 4


class GenerateColoringResponse(BaseModel):
    """Response for coloring generation."""

    queued: int
    message: str


async def _get_next_coloring_version(session: AsyncSession, image_id: int) -> int:
    """Get the next version number for a coloring version."""
    from sqlalchemy import func

    result = await session.execute(
        select(func.coalesce(func.max(ColoringVersion.version), 0)).where(ColoringVersion.image_id == image_id)
    )
    max_version = result.scalar() or 0
    return max_version + 1


async def _get_next_svg_version(session: AsyncSession, image_id: int) -> int:
    """Get the next version number for an SVG version (across all colorings for this image)."""
    from sqlalchemy import func

    # Get all coloring versions for this image
    coloring_ids_result = await session.execute(select(ColoringVersion.id).where(ColoringVersion.image_id == image_id))
    coloring_ids = [row[0] for row in coloring_ids_result.fetchall()]

    if not coloring_ids:
        return 1

    result = await session.execute(
        select(func.coalesce(func.max(SvgVersion.version), 0)).where(SvgVersion.coloring_version_id.in_(coloring_ids))  # type: ignore[attr-defined]
    )
    max_version = result.scalar() or 0
    return max_version + 1


@router.post("/orders/{order_number}/generate-coloring", response_model=GenerateColoringResponse)
async def generate_order_coloring(
    order_number: str,
    request: GenerateColoringRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> GenerateColoringResponse:
    """Generate coloring books for all images in an order."""
    normalized_number = normalize_order_number(order_number)
    req = request or GenerateColoringRequest()

    # Get order with all images and their coloring versions
    statement = (
        select(Order)
        .options(
            selectinload(Order.line_items)  # type: ignore[arg-type]
            .selectinload(LineItem.images)  # type: ignore[arg-type]
            .selectinload(Image.coloring_versions)  # type: ignore[arg-type]
        )
        .where(Order.shopify_order_number == normalized_number)
    )
    result = await session.execute(statement)
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Collect images that need coloring generation:
    # - Must be downloaded
    # - Must NOT already have a completed coloring version
    # - Must NOT be currently processing
    images_to_process: list[Image] = []
    for li in order.line_items:
        for img in li.images:
            if not img.local_path:  # Skip images not yet downloaded
                continue
            # Check if already has a completed coloring version
            has_completed = any(cv.status == ImageProcessingStatus.COMPLETED for cv in img.coloring_versions)
            if has_completed:
                continue  # Skip - already has coloring
            # Check if any coloring version is currently queued or processing
            is_processing = any(
                cv.status in (ImageProcessingStatus.QUEUED, ImageProcessingStatus.PROCESSING)
                for cv in img.coloring_versions
            )
            if is_processing:
                continue  # Skip - already processing
            images_to_process.append(img)

    if not images_to_process:
        raise HTTPException(
            status_code=400,
            detail="No images need coloring generation. All images either have coloring or are processing.",
        )

    # Create coloring versions and enqueue tasks
    queued = 0
    for image in images_to_process:
        assert image.id is not None
        next_version = await _get_next_coloring_version(session, image.id)

        coloring_version = ColoringVersion(
            image_id=image.id,
            version=next_version,
            status=ImageProcessingStatus.QUEUED,
            megapixels=req.megapixels,
            steps=req.steps,
        )
        session.add(coloring_version)
        await session.flush()

        assert coloring_version.id is not None
        generate_coloring.send(coloring_version.id)
        queued += 1

    await session.commit()

    return GenerateColoringResponse(
        queued=queued,
        message=f"Queued {queued} images for coloring generation",
    )


@router.post("/images/{image_id}/generate-coloring", response_model=ColoringVersionResponse)
async def generate_image_coloring(
    image_id: int,
    request: GenerateColoringRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> ColoringVersionResponse:
    """Generate a coloring book for a single image."""
    req = request or GenerateColoringRequest()

    image = await session.get(Image, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    if not image.local_path:
        raise HTTPException(
            status_code=400,
            detail="Image not downloaded yet. Please download the image first.",
        )

    # Create coloring version
    next_version = await _get_next_coloring_version(session, image_id)

    coloring_version = ColoringVersion(
        image_id=image_id,
        version=next_version,
        status=ImageProcessingStatus.QUEUED,
        megapixels=req.megapixels,
        steps=req.steps,
    )
    session.add(coloring_version)
    await session.flush()

    assert coloring_version.id is not None
    generate_coloring.send(coloring_version.id)

    await session.commit()

    return ColoringVersionResponse(
        id=coloring_version.id,
        version=coloring_version.version,
        file_path=coloring_version.file_path,
        status=coloring_version.status,
        megapixels=coloring_version.megapixels,
        steps=coloring_version.steps,
        created_at=coloring_version.created_at,
    )


# =============================================================================
# SVG Generation Endpoints
# =============================================================================


class GenerateSvgRequest(BaseModel):
    """Request body for SVG generation."""

    shape_stacking: str = "stacked"
    group_by: str = "color"


class GenerateSvgResponse(BaseModel):
    """Response for SVG generation."""

    queued: int
    message: str


def _find_coloring_for_svg(image: Image) -> ColoringVersion | None:
    """Find the best coloring version to use for SVG generation.

    Prefers the selected coloring version, falls back to latest completed.
    """
    # Try selected coloring first
    if image.selected_coloring_id:
        for cv in image.coloring_versions:
            if cv.id == image.selected_coloring_id and cv.status == ImageProcessingStatus.COMPLETED:
                return cv

    # Fall back to latest completed coloring
    completed = [cv for cv in image.coloring_versions if cv.status == ImageProcessingStatus.COMPLETED]
    if completed:
        return max(completed, key=lambda x: x.version)

    return None


@router.post("/orders/{order_number}/generate-svg", response_model=GenerateSvgResponse)
async def generate_order_svg(
    order_number: str,
    request: GenerateSvgRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> GenerateSvgResponse:
    """Generate SVGs for all images in an order that don't have SVG yet."""
    normalized_number = normalize_order_number(order_number)
    req = request or GenerateSvgRequest()

    # Get order with all images, coloring versions, and their SVG versions
    statement = (
        select(Order)
        .options(
            selectinload(Order.line_items)  # type: ignore[arg-type]
            .selectinload(LineItem.images)  # type: ignore[arg-type]
            .selectinload(Image.coloring_versions)  # type: ignore[arg-type]
            .selectinload(ColoringVersion.svg_versions)  # type: ignore[arg-type]
        )
        .where(Order.shopify_order_number == normalized_number)
    )
    result = await session.execute(statement)
    order = result.scalars().first()
    if not order:
        raise HTTPException(status_code=404, detail="Order not found")

    # Collect images that need SVG generation:
    # - Must have completed coloring
    # - Must NOT already have a completed SVG
    # - Must NOT be currently processing SVG
    queued = 0
    for li in order.line_items:
        for img in li.images:
            coloring_to_use = _find_coloring_for_svg(img)
            if not coloring_to_use:
                continue

            # Check if image already has any completed SVG (from any coloring version)
            has_completed_svg = any(
                sv.status == ImageProcessingStatus.COMPLETED for cv in img.coloring_versions for sv in cv.svg_versions
            )
            if has_completed_svg:
                continue  # Skip - already has SVG

            # Check if any SVG is currently queued or processing
            is_svg_processing = any(
                sv.status in (ImageProcessingStatus.QUEUED, ImageProcessingStatus.PROCESSING)
                for cv in img.coloring_versions
                for sv in cv.svg_versions
            )
            if is_svg_processing:
                continue  # Skip - already processing SVG

            assert img.id is not None
            assert coloring_to_use.id is not None
            next_version = await _get_next_svg_version(session, img.id)

            svg_version = SvgVersion(
                coloring_version_id=coloring_to_use.id,
                version=next_version,
                status=ImageProcessingStatus.QUEUED,
                shape_stacking=req.shape_stacking,
                group_by=req.group_by,
            )
            session.add(svg_version)
            await session.flush()

            assert svg_version.id is not None
            vectorize_image.send(svg_version.id)
            queued += 1

    if queued == 0:
        raise HTTPException(
            status_code=400,
            detail="No images need SVG generation. All images either have SVG, are processing, or have no coloring.",
        )

    await session.commit()

    return GenerateSvgResponse(
        queued=queued,
        message=f"Queued {queued} images for SVG generation",
    )


@router.post("/images/{image_id}/generate-svg", response_model=SvgVersionResponse)
async def generate_image_svg(
    image_id: int,
    request: GenerateSvgRequest | None = None,
    session: AsyncSession = Depends(get_session),
) -> SvgVersionResponse:
    """Generate an SVG for a single image from its selected coloring version."""
    req = request or GenerateSvgRequest()

    # Get image with coloring versions
    statement = (
        select(Image)
        .options(selectinload(Image.coloring_versions))  # type: ignore[arg-type]
        .where(Image.id == image_id)
    )
    result = await session.execute(statement)
    image = result.scalars().first()

    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    # Find coloring version to use
    coloring_to_use = _find_coloring_for_svg(image)

    if not coloring_to_use:
        raise HTTPException(
            status_code=400,
            detail="No completed coloring version found. Generate a coloring book first.",
        )

    # Create SVG version
    next_version = await _get_next_svg_version(session, image_id)

    svg_version = SvgVersion(
        coloring_version_id=coloring_to_use.id,
        version=next_version,
        status=ImageProcessingStatus.QUEUED,
        shape_stacking=req.shape_stacking,
        group_by=req.group_by,
    )
    session.add(svg_version)
    await session.flush()

    assert svg_version.id is not None
    vectorize_image.send(svg_version.id)

    await session.commit()

    return SvgVersionResponse(
        id=svg_version.id,
        version=svg_version.version,
        file_path=svg_version.file_path,
        status=svg_version.status,
        coloring_version_id=svg_version.coloring_version_id,
        shape_stacking=svg_version.shape_stacking,
        group_by=svg_version.group_by,
        created_at=svg_version.created_at,
    )


# =============================================================================
# Version Listing Endpoints
# =============================================================================


@router.get("/images/{image_id}/coloring-versions", response_model=list[ColoringVersionResponse])
async def list_coloring_versions(
    image_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[ColoringVersionResponse]:
    """List all coloring versions for an image."""
    statement = (
        select(ColoringVersion).where(ColoringVersion.image_id == image_id).order_by(ColoringVersion.version.desc())  # type: ignore[attr-defined]
    )
    result = await session.execute(statement)
    versions = result.scalars().all()

    return [
        ColoringVersionResponse(
            id=v.id,  # type: ignore[arg-type]
            version=v.version,
            file_path=v.file_path,
            status=v.status,
            megapixels=v.megapixels,
            steps=v.steps,
            created_at=v.created_at,
        )
        for v in versions
    ]


@router.get("/images/{image_id}/svg-versions", response_model=list[SvgVersionResponse])
async def list_svg_versions(
    image_id: int,
    session: AsyncSession = Depends(get_session),
) -> list[SvgVersionResponse]:
    """List all SVG versions for an image (across all coloring versions)."""
    # First get all coloring version IDs for this image
    coloring_ids_result = await session.execute(select(ColoringVersion.id).where(ColoringVersion.image_id == image_id))
    coloring_ids = [row[0] for row in coloring_ids_result.fetchall()]

    if not coloring_ids:
        return []

    statement = (
        select(SvgVersion)
        .where(SvgVersion.coloring_version_id.in_(coloring_ids))  # type: ignore[attr-defined]
        .order_by(SvgVersion.version.desc())  # type: ignore[attr-defined]
    )
    result = await session.execute(statement)
    versions = result.scalars().all()

    return [
        SvgVersionResponse(
            id=v.id,  # type: ignore[arg-type]
            version=v.version,
            file_path=v.file_path,
            status=v.status,
            coloring_version_id=v.coloring_version_id,
            shape_stacking=v.shape_stacking,
            group_by=v.group_by,
            created_at=v.created_at,
        )
        for v in versions
    ]


# =============================================================================
# Version Selection Endpoints
# =============================================================================


@router.post("/images/{image_id}/select-coloring/{version_id}")
async def select_coloring_version(
    image_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Select a coloring version as the default for an image."""
    image = await session.get(Image, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    coloring_version = await session.get(ColoringVersion, version_id)
    if not coloring_version:
        raise HTTPException(status_code=404, detail="Coloring version not found")

    if coloring_version.image_id != image_id:
        raise HTTPException(
            status_code=400,
            detail="Coloring version does not belong to this image",
        )

    image.selected_coloring_id = version_id
    await session.commit()

    return {"status": "ok", "message": f"Selected coloring version {version_id}"}


@router.post("/images/{image_id}/select-svg/{version_id}")
async def select_svg_version(
    image_id: int,
    version_id: int,
    session: AsyncSession = Depends(get_session),
) -> dict[str, str]:
    """Select an SVG version as the default for an image."""
    image = await session.get(Image, image_id)
    if not image:
        raise HTTPException(status_code=404, detail="Image not found")

    svg_version = await session.get(SvgVersion, version_id)
    if not svg_version:
        raise HTTPException(status_code=404, detail="SVG version not found")

    # Verify SVG belongs to a coloring version for this image
    coloring_version = await session.get(ColoringVersion, svg_version.coloring_version_id)
    if not coloring_version or coloring_version.image_id != image_id:
        raise HTTPException(
            status_code=400,
            detail="SVG version does not belong to this image",
        )

    image.selected_svg_id = version_id
    await session.commit()

    return {"status": "ok", "message": f"Selected SVG version {version_id}"}


# =============================================================================
# Retry Endpoints
# =============================================================================


@router.post("/coloring-versions/{version_id}/retry", response_model=ColoringVersionResponse)
async def retry_coloring_version(
    version_id: int,
    session: AsyncSession = Depends(get_session),
) -> ColoringVersionResponse:
    """Retry a failed coloring version generation with the same settings."""
    coloring_version = await session.get(ColoringVersion, version_id)
    if not coloring_version:
        raise HTTPException(status_code=404, detail="Coloring version not found")

    if coloring_version.status != ImageProcessingStatus.ERROR:
        raise HTTPException(
            status_code=400,
            detail="Can only retry versions with error status",
        )

    # Reset status to QUEUED and re-dispatch the task
    coloring_version.status = ImageProcessingStatus.QUEUED
    await session.commit()

    assert coloring_version.id is not None
    generate_coloring.send(coloring_version.id)

    return ColoringVersionResponse(
        id=coloring_version.id,
        version=coloring_version.version,
        file_path=coloring_version.file_path,
        status=coloring_version.status,
        megapixels=coloring_version.megapixels,
        steps=coloring_version.steps,
        created_at=coloring_version.created_at,
    )


@router.post("/svg-versions/{version_id}/retry", response_model=SvgVersionResponse)
async def retry_svg_version(
    version_id: int,
    session: AsyncSession = Depends(get_session),
) -> SvgVersionResponse:
    """Retry a failed SVG version generation with the same settings."""
    svg_version = await session.get(SvgVersion, version_id)
    if not svg_version:
        raise HTTPException(status_code=404, detail="SVG version not found")

    if svg_version.status != ImageProcessingStatus.ERROR:
        raise HTTPException(
            status_code=400,
            detail="Can only retry versions with error status",
        )

    # Reset status to QUEUED and re-dispatch the task
    svg_version.status = ImageProcessingStatus.QUEUED
    await session.commit()

    assert svg_version.id is not None
    vectorize_image.send(svg_version.id)

    return SvgVersionResponse(
        id=svg_version.id,
        version=svg_version.version,
        file_path=svg_version.file_path,
        status=svg_version.status,
        coloring_version_id=svg_version.coloring_version_id,
        shape_stacking=svg_version.shape_stacking,
        group_by=svg_version.group_by,
        created_at=svg_version.created_at,
    )


# =============================================================================
# File Serving Endpoints
# =============================================================================


@router.get("/coloring-versions/{version_id}/file")
async def get_coloring_file(
    version_id: int,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Serve a coloring version PNG file."""
    coloring_version = await session.get(ColoringVersion, version_id)
    if not coloring_version:
        raise HTTPException(status_code=404, detail="Coloring version not found")

    if not coloring_version.file_path:
        raise HTTPException(status_code=404, detail="Coloring file not generated yet")

    file_path = Path(coloring_version.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Coloring file not found")

    return FileResponse(file_path, media_type="image/png")


@router.get("/svg-versions/{version_id}/file")
async def get_svg_file(
    version_id: int,
    session: AsyncSession = Depends(get_session),
) -> FileResponse:
    """Serve an SVG version file."""
    svg_version = await session.get(SvgVersion, version_id)
    if not svg_version:
        raise HTTPException(status_code=404, detail="SVG version not found")

    if not svg_version.file_path:
        raise HTTPException(status_code=404, detail="SVG file not generated yet")

    file_path = Path(svg_version.file_path)
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="SVG file not found")

    return FileResponse(file_path, media_type="image/svg+xml")
