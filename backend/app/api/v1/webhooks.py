"""Shopify webhook endpoints."""

import hashlib
import hmac
from base64 import b64encode

import structlog
from fastapi import APIRouter, HTTPException, Request, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.db import async_session_maker
from app.models.enums import OrderStatus
from app.models.order import Order
from app.services.external.mercure import MercureService
from app.tasks.orders.order_ingestion import ingest_order

logger = structlog.get_logger(__name__)

router = APIRouter()


def verify_shopify_hmac(body: bytes, hmac_header: str | None) -> bool:
    """
    Verify Shopify webhook HMAC signature.

    Args:
        body: Raw request body bytes
        hmac_header: X-Shopify-Hmac-Sha256 header value

    Returns:
        True if signature is valid, False otherwise
    """
    if not hmac_header or not settings.shopify_webhook_secret:
        return False

    computed_hmac = b64encode(
        hmac.new(
            settings.shopify_webhook_secret.encode("utf-8"),
            body,
            hashlib.sha256,
        ).digest()
    ).decode("utf-8")

    return hmac.compare_digest(computed_hmac, hmac_header)


async def save_or_get_order(payload: dict[str, object], session: AsyncSession) -> Order:
    """
    Save a new order or get existing one (idempotent).

    Uses shopify_id as unique key to prevent duplicate orders
    from duplicate webhook deliveries.
    """
    from typing import cast

    from sqlmodel import select

    shopify_id = payload.get("id")
    if not shopify_id:
        raise ValueError("Missing order ID in payload")

    # Check if order already exists
    statement = select(Order).where(Order.shopify_id == cast(int, shopify_id))
    result = await session.execute(statement)
    existing_order = result.scalar_one_or_none()

    if existing_order:
        logger.info("Order already exists", shopify_id=shopify_id, order_id=existing_order.id)
        return existing_order

    # Extract customer info
    customer_data = payload.get("customer")
    customer_name: str | None = None
    if isinstance(customer_data, dict):
        first_name = customer_data.get("first_name", "")
        customer_name = str(first_name) if first_name else None

    # Create new order
    # Use "name" field (e.g., "#1270") for both order_number and shopify_order_number
    shopify_order_number = str(payload.get("name", ""))
    email = payload.get("email")

    order = Order(
        order_number=shopify_order_number,  # Display value (same as shopify_order_number for Shopify orders)
        shopify_id=cast(int, shopify_id),
        shopify_order_number=shopify_order_number,
        customer_email=str(email) if email else None,
        customer_name=customer_name,
        status=OrderStatus.PENDING,
    )
    session.add(order)
    await session.commit()
    await session.refresh(order)

    logger.info("Created new order", shopify_id=shopify_id, order_id=order.id)

    # Notify frontend about new order via Mercure
    mercure = MercureService()
    await mercure.publish_order_list_update()

    return order


@router.post("/webhooks/shopify")
async def shopify_webhook(request: Request) -> Response:
    """
    Handle Shopify order webhooks.

    1. Verify HMAC signature
    2. Save order to database (idempotent)
    3. Enqueue background processing task
    4. Return 200 immediately

    The actual processing happens in the background via Dramatiq.
    """
    # Read body first (before any async operations)
    body = await request.body()

    # Verify HMAC
    hmac_header = request.headers.get("X-Shopify-Hmac-Sha256")
    if not verify_shopify_hmac(body, hmac_header):
        logger.warning("Invalid Shopify webhook HMAC")
        raise HTTPException(status_code=401, detail="Invalid HMAC signature")

    # Parse payload
    try:
        import json

        payload = json.loads(body)
    except json.JSONDecodeError as e:
        logger.error("Invalid JSON in webhook payload", error=str(e))
        raise HTTPException(status_code=400, detail="Invalid JSON payload") from e

    # Save order (idempotent)
    async with async_session_maker() as session:
        order = await save_or_get_order(payload, session)

        # Only enqueue if order is pending (not already being processed)
        if order.status == OrderStatus.PENDING:
            ingest_order.send(order.id)
            logger.info("Enqueued order for processing", order_id=order.id)

    # Return 200 immediately (Shopify expects fast response)
    return Response(status_code=200)
