"""Mercure SSE publishing service."""

from typing import Literal

import httpx
import jwt
import structlog

from app.config import settings
from app.models.events import (
    ImageStatusEvent,
    ImageUpdateEvent,
    ListUpdateEvent,
    OrderUpdateEvent,
)

logger = structlog.get_logger(__name__)


class MercureService:
    """Service for publishing events to Mercure SSE hub."""

    def _create_jwt(self) -> str:
        """Create a JWT token for publishing to Mercure.

        The token grants permission to publish to any topic.
        """
        return jwt.encode(
            {"mercure": {"publish": ["*"]}},
            settings.mercure_publisher_jwt_key,
            algorithm="HS256",
        )

    async def _publish(
        self,
        topics: list[str] | str,
        data: str,
        *,
        context: dict[str, str | int] | None = None,
    ) -> bool:
        """Publish a message to Mercure hub.

        Args:
            topics: Topic(s) to publish to (string or list of strings)
            data: JSON data to publish
            context: Optional context for logging (e.g., order_id)

        Returns:
            True if published successfully, False otherwise
        """
        token = self._create_jwt()
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

    async def publish_order_update(self, order_id: str) -> bool:
        """Publish an order update event to Mercure.

        This sends a lightweight "ping" to notify connected clients
        that an order has been updated. Clients should then refetch
        the order data from the API.

        Args:
            order_id: The order ID (ULID string)

        Returns:
            True if published successfully, False otherwise
        """
        event = OrderUpdateEvent(type="order_update", order_id=order_id)

        return await self._publish(
            topics=["orders", f"orders/{order_id}"],
            data=event.model_dump_json(),
            context={"order_id": order_id},
        )

    async def publish_order_list_update(self) -> bool:
        """Publish a general order list update event.

        Used when a new order is created or an order is deleted.
        """
        event = ListUpdateEvent(type="list_update")
        return await self._publish(
            topics="orders",
            data=event.model_dump_json(),
        )

    async def publish_image_update(
        self,
        order_id: str,
        image_id: int,
    ) -> bool:
        """Publish a general update event for a specific image.

        Used when image metadata changes (e.g., selection changes) to notify
        clients to refetch the image data.

        Args:
            order_id: The order ID (ULID string)
            image_id: Database ID of the Image record

        Returns:
            True if published successfully, False otherwise
        """
        event = ImageUpdateEvent(
            type="image_update",
            order_id=order_id,
            image_id=image_id,
        )

        return await self._publish(
            topics=["orders", f"orders/{order_id}"],
            data=event.model_dump_json(),
            context={
                "order_id": order_id,
                "image_id": image_id,
            },
        )

    async def publish_image_status(
        self,
        order_id: str,
        image_id: int,
        status_type: Literal["coloring", "svg"],
        version_id: int,
        status: str,
    ) -> bool:
        """Publish a granular status update for a specific image.

        This is used during processing to notify clients of status changes
        without requiring a full order refetch. Clients should fetch only
        the updated image data.

        Args:
            order_id: The order ID (ULID string)
            image_id: Database ID of the Image record
            status_type: Either "coloring" or "svg"
            version_id: Database ID of ColoringVersion or SvgVersion
            status: The new status value

        Returns:
            True if published successfully, False otherwise
        """
        event = ImageStatusEvent(
            type="image_status",
            order_id=order_id,
            image_id=image_id,
            status_type=status_type,
            version_id=version_id,
            status=status,
        )

        return await self._publish(
            topics=["orders", f"orders/{order_id}"],
            data=event.model_dump_json(),
            context={
                "order_id": order_id,
                "image_id": image_id,
                "status_type": status_type,
                "version_id": version_id,
                "status": status,
            },
        )
