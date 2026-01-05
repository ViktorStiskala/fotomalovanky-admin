"""Dramatiq background tasks package."""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.config import settings

# Configure Redis broker
redis_broker = RedisBroker(url=settings.redis_url)  # type: ignore[no-untyped-call]
dramatiq.set_broker(redis_broker)

# Import and re-export all tasks (must be after broker setup)
from app.tasks.image_download import download_order_images  # noqa: E402
from app.tasks.order_ingestion import ingest_order  # noqa: E402

__all__ = ["ingest_order", "download_order_images"]
