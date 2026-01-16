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

# Import and re-export all tasks (must be after broker setup)
from app.tasks.image_download import download_order_images  # noqa: E402
from app.tasks.order_ingestion import ingest_order  # noqa: E402
from app.tasks.process.generate_coloring import generate_coloring  # noqa: E402
from app.tasks.process.vectorize_image import vectorize_image  # noqa: E402

__all__ = ["ingest_order", "download_order_images", "generate_coloring", "vectorize_image"]
