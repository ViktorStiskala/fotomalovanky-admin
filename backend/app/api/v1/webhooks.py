"""Shopify webhook endpoints."""

import hashlib
import hmac
from base64 import b64encode

import structlog
from fastapi import APIRouter, HTTPException, Request, Response

from app.config import settings
from app.db import async_session_maker
from app.models.enums import OrderStatus
from app.services.orders.order_service import OrderService
from app.tasks.orders.fetch_shopify_order import ingest_order

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

    # Save order (idempotent) using OrderService
    async with async_session_maker() as session:
        order_service = OrderService(session)
        order, _is_new = await order_service.get_or_create_from_webhook(payload)
        await session.commit()
        # ListUpdateEvent is auto-published on commit via trigger_models if Order was created

        # Only enqueue if order is pending (not already being processed)
        if order.status == OrderStatus.PENDING:
            ingest_order.send(order.id)
            logger.info("Enqueued order for processing", order_id=order.id)

    # Return 200 immediately (Shopify expects fast response)
    return Response(status_code=200)
