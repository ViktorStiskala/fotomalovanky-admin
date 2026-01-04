"""Mercure SSE publishing service."""

import httpx
import jwt
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def create_mercure_jwt() -> str:
    """
    Create a JWT token for publishing to Mercure.

    The token grants permission to publish to any topic.
    """
    return jwt.encode(
        {"mercure": {"publish": ["*"]}},
        settings.mercure_publisher_jwt_key,
        algorithm="HS256",
    )


async def publish_order_update(order_id: int) -> bool:
    """
    Publish an order update event to Mercure.

    This sends a lightweight "ping" to notify connected clients
    that an order has been updated. Clients should then refetch
    the order data from the API.

    Args:
        order_id: The ID of the updated order

    Returns:
        True if published successfully, False otherwise
    """
    token = create_mercure_jwt()

    async with httpx.AsyncClient() as client:
        try:
            # Publish to both general orders topic and specific order topic
            response = await client.post(
                settings.mercure_url,
                data={
                    "topic": ["orders", f"orders/{order_id}"],
                    "data": f'{{"type": "order_update", "id": {order_id}}}',
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=10.0,
            )
            response.raise_for_status()

            logger.info("Published order update to Mercure", order_id=order_id)
            return True

        except httpx.HTTPStatusError as e:
            logger.error(
                "Failed to publish to Mercure",
                status_code=e.response.status_code,
                order_id=order_id,
            )
            return False
        except httpx.RequestError as e:
            logger.error("Mercure request failed", error=str(e), order_id=order_id)
            return False


async def publish_order_list_update() -> bool:
    """
    Publish a general order list update event.

    Used when a new order is created or an order is deleted.
    """
    token = create_mercure_jwt()

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                settings.mercure_url,
                data={
                    "topic": "orders",
                    "data": '{"type": "list_update"}',
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=10.0,
            )
            response.raise_for_status()

            logger.info("Published order list update to Mercure")
            return True

        except httpx.HTTPStatusError as e:
            logger.error("Failed to publish to Mercure", status_code=e.response.status_code)
            return False
        except httpx.RequestError as e:
            logger.error("Mercure request failed", error=str(e))
            return False
