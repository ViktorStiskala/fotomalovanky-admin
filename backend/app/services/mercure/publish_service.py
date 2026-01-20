"""Mercure publishing service."""

import httpx
import jwt
import structlog

from app.config import settings
from app.services.mercure.events import BaseMercureEvent
from app.utils.request_retry import RequestRetryConfig, get_request_retrying

logger = structlog.get_logger(__name__)

# Retry config for Mercure publishing (quick retries, short waits)
MERCURE_RETRY_CONFIG = RequestRetryConfig(max_attempts=3, min_wait=0.5, max_wait=2.0)


class MercurePublishService:
    """Service for publishing events to Mercure hub.

    This service handles the low-level details of publishing events to Mercure:
    - JWT token generation for authentication
    - HTTP POST to the Mercure hub
    - Error handling and logging

    Events know their own topics via get_topics(), so this service just needs
    to publish whatever event is given to it.

    Usage:
        mercure = MercurePublishService()
        await mercure.publish(OrderUpdateEvent(order_id="abc123"))
        await mercure.publish(ListUpdateEvent(order_ids=["abc", "def"]))
    """

    def _create_jwt(self) -> str:
        """Create a JWT token for publishing to Mercure.

        The token grants permission to publish to any topic.
        """
        return jwt.encode(
            {"mercure": {"publish": ["*"]}},
            settings.mercure_publisher_jwt_key,
            algorithm="HS256",
        )

    async def publish(self, event: BaseMercureEvent) -> None:
        """Publish any Mercure event.

        The event knows its own topics via get_topics().
        Retries on network errors, logs and swallows errors after retries exhausted.

        Args:
            event: Any BaseMercureEvent subclass instance
        """
        if not settings.mercure_publisher_jwt_key:
            logger.warning("Mercure publisher JWT key not configured, skipping publish")
            return

        topics = event.get_topics()
        token = self._create_jwt()

        async def make_request(client: httpx.AsyncClient) -> None:
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

        try:
            async with httpx.AsyncClient() as client:
                async for attempt in get_request_retrying(MERCURE_RETRY_CONFIG):
                    with attempt:
                        if attempt.retry_state.attempt_number > 1:
                            logger.warning(
                                "Retrying Mercure publish",
                                topics=topics,
                                attempt=attempt.retry_state.attempt_number,
                            )
                        await make_request(client)

            logger.info("Published Mercure event", topics=topics, type=event.type)
        except Exception as e:
            # Log and swallow - publishing failures shouldn't crash the application
            logger.error("Failed to publish Mercure event", error=str(e), topics=topics)
