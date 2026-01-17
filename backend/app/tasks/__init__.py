"""Dramatiq background tasks package."""

import dramatiq
from dramatiq.brokers.redis import RedisBroker
from dramatiq.middleware import Middleware

from app.config import settings


class TaskRecoveryMiddleware(Middleware):
    """Middleware that recovers stuck tasks on worker boot."""

    _recovered = False

    def before_worker_boot(self, broker: dramatiq.Broker, worker: dramatiq.Worker) -> None:
        """Run task recovery once when worker starts."""
        # Only run recovery once per process
        if TaskRecoveryMiddleware._recovered:
            return
        TaskRecoveryMiddleware._recovered = True

        from app.tasks.recovery import recover_stuck_tasks

        recover_stuck_tasks()


# Configure Redis broker
redis_broker = RedisBroker(url=settings.redis_url)  # type: ignore[no-untyped-call]
redis_broker.add_middleware(TaskRecoveryMiddleware())
dramatiq.set_broker(redis_broker)

# Import all tasks to register them with Dramatiq (must be after broker setup)
# These imports are required for task discovery, not for re-export
import app.tasks.orders.fetch_shopify  # noqa: E402, F401
import app.tasks.orders.image_download  # noqa: E402, F401
import app.tasks.orders.order_ingestion  # noqa: E402, F401
import app.tasks.coloring.generate_coloring  # noqa: E402, F401
import app.tasks.coloring.vectorize_image  # noqa: E402, F401
