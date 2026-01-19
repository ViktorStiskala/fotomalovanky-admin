"""Mercure publishing service."""

from typing import Literal

import httpx
import jwt
import structlog

from app.config import settings
from app.models.events import (
    ImageStatusEvent,
    ImageUpdateEvent,
    ListUpdateEvent,
    MercureEvent,
    OrderUpdateEvent,
)

logger = structlog.get_logger(__name__)


class MercurePublishService:
    """Service for publishing events to Mercure hub."""

    def _create_jwt(self) -> str:
        """Create a JWT token for publishing to Mercure.

        The token grants permission to publish to any topic.
        """
        return jwt.encode(
            {"mercure": {"publish": ["*"]}},
            settings.mercure_publisher_jwt_key,
            algorithm="HS256",
        )

    async def _publish(self, topics: list[str], event: MercureEvent) -> None:
        """Publish an event to Mercure topics."""
        if not settings.mercure_publisher_jwt_key:
            logger.warning("Mercure publisher JWT key not configured, skipping publish")
            return

        token = self._create_jwt()

        async with httpx.AsyncClient() as client:
            try:
                # Mercure expects form data
                data = {
                    "topic": topics,
                    "data": event.model_dump_json(),
                }
                response = await client.post(
                    settings.mercure_url,
                    data=data,
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=5.0,
                )
                response.raise_for_status()
                logger.debug("Published Mercure event", topics=topics, type=event.type)
            except Exception as e:
                logger.error("Failed to publish Mercure event", error=str(e), topics=topics)

    async def publish_order_update(self, order_id: str) -> None:
        """Publish order update event."""
        event = OrderUpdateEvent(type="order_update", order_id=order_id)
        await self._publish(
            topics=["orders", f"orders/{order_id}"],
            event=event,
        )

    async def publish_order_list_update(self) -> None:
        """Publish order list update event."""
        event = ListUpdateEvent(type="list_update")
        await self._publish(topics=["orders"], event=event)

    async def publish_image_update(self, order_id: str, image_id: int) -> None:
        """Publish image update event."""
        event = ImageUpdateEvent(type="image_update", order_id=order_id, image_id=image_id)
        await self._publish(
            topics=["orders", f"orders/{order_id}"],
            event=event,
        )

    async def publish_image_status(
        self,
        order_id: str,
        image_id: int,
        status_type: Literal["coloring", "svg"],
        version_id: int,
        status: str,
    ) -> None:
        """Publish image processing status event."""
        event = ImageStatusEvent(
            type="image_status",
            order_id=order_id,
            image_id=image_id,
            status_type=status_type,
            version_id=version_id,
            status=status,
        )
        await self._publish(
            topics=["orders", f"orders/{order_id}"],
            event=event,
        )
