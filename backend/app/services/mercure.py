"""Mercure SSE publishing service."""

import json
from typing import Literal

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


async def _publish_to_mercure(
    topics: list[str] | str,
    data: str,
    *,
    context: dict[str, str | int] | None = None,
) -> bool:
    """
    Publish a message to Mercure hub.

    Args:
        topics: Topic(s) to publish to (string or list of strings)
        data: JSON data to publish
        context: Optional context for logging (e.g., order_number)

    Returns:
        True if published successfully, False otherwise
    """
    token = create_mercure_jwt()
    log_context = context or {}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                settings.mercure_url,
                data={
                    "topic": topics,
                    "data": data,
                },
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/x-www-form-urlencoded",
                },
                timeout=10.0,
            )
            response.raise_for_status()

            logger.info("Published to Mercure", topics=topics, **log_context)
            return True

        except httpx.HTTPStatusError as e:
            logger.error(
                "Failed to publish to Mercure",
                status_code=e.response.status_code,
                topics=topics,
                **log_context,
            )
            return False
        except httpx.RequestError as e:
            logger.error(
                "Mercure request failed",
                error=str(e),
                topics=topics,
                **log_context,
            )
            return False


async def publish_order_update(order_number: str) -> bool:
    """
    Publish an order update event to Mercure.

    This sends a lightweight "ping" to notify connected clients
    that an order has been updated. Clients should then refetch
    the order data from the API.

    Args:
        order_number: The Shopify order number (e.g., "1270" without the "#")

    Returns:
        True if published successfully, False otherwise
    """
    return await _publish_to_mercure(
        topics=["orders", f"orders/{order_number}"],
        data=f'{{"type": "order_update", "order_number": "{order_number}"}}',
        context={"order_number": order_number},
    )


async def publish_order_list_update() -> bool:
    """
    Publish a general order list update event.

    Used when a new order is created or an order is deleted.
    """
    return await _publish_to_mercure(
        topics="orders",
        data='{"type": "list_update"}',
    )


async def publish_image_status(
    order_number: str,
    image_id: int,
    status_type: Literal["coloring", "svg"],
    version_id: int,
    status: str,
) -> bool:
    """
    Publish a granular status update for a specific image.

    This is used during processing to notify clients of status changes
    without requiring a full order refetch. Clients should fetch only
    the updated image data.

    Args:
        order_number: The Shopify order number (e.g., "1270" without the "#")
        image_id: Database ID of the Image record
        status_type: Either "coloring" or "svg"
        version_id: Database ID of ColoringVersion or SvgVersion
        status: The new status value

    Returns:
        True if published successfully, False otherwise
    """
    data = json.dumps(
        {
            "type": "image_status",
            "order_number": order_number,
            "image_id": image_id,
            "status_type": status_type,
            "version_id": version_id,
            "status": status,
        }
    )

    return await _publish_to_mercure(
        topics=["orders", f"orders/{order_number}"],
        data=data,
        context={
            "order_number": order_number,
            "image_id": image_id,
            "status_type": status_type,
            "version_id": version_id,
            "status": status,
        },
    )
