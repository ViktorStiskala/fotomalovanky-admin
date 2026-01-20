"""Dramatiq background tasks package."""

import dramatiq
import redis
import structlog
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Middleware

from app.config import settings
from app.logging import setup_logging

# Configure logging before anything else
setup_logging()

logger = structlog.get_logger(__name__)

# Recovery lock settings
RECOVERY_LOCK_KEY = "dramatiq:recovery:lock"
RECOVERY_LOCK_TTL = 60  # seconds


class TaskRecoveryMiddleware(Middleware):
    """Middleware that recovers stuck tasks on worker boot."""

    _recovered = False

    def before_worker_boot(self, broker: dramatiq.Broker, worker: dramatiq.Worker) -> None:
        """Run task recovery once when worker starts.

        Uses a Redis lock to ensure only one worker across all processes
        runs recovery at a time.
        """
        # Only run recovery once per process
        if TaskRecoveryMiddleware._recovered:
            return
        TaskRecoveryMiddleware._recovered = True

        # Try to acquire distributed lock via Redis
        r = redis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
        lock_acquired = r.set(RECOVERY_LOCK_KEY, "1", nx=True, ex=RECOVERY_LOCK_TTL)

        if not lock_acquired:
            logger.debug("Recovery lock held by another worker, skipping")
            return

        try:
            from app.tasks.recovery import recover_stuck_tasks

            recover_stuck_tasks()
        finally:
            # Release lock when done
            r.delete(RECOVERY_LOCK_KEY)


# Configure Redis broker
redis_broker = RedisBroker(url=settings.redis_url)  # type: ignore[no-untyped-call]
redis_broker.add_middleware(TaskRecoveryMiddleware())
dramatiq.set_broker(redis_broker)

# Import all tasks to register them with Dramatiq (must be after broker setup)
# These imports are required for task discovery, not for re-export
import app.tasks.coloring.generate_coloring  # noqa: E402, F401
import app.tasks.coloring.vectorize_image  # noqa: E402, F401
import app.tasks.orders.fetch_shopify  # noqa: E402, F401
import app.tasks.orders.image_download  # noqa: E402, F401
import app.tasks.orders.order_ingestion  # noqa: E402, F401
