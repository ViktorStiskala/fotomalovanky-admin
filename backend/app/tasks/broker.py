"""Dramatiq broker configuration."""

import dramatiq
from dramatiq.brokers.redis import RedisBroker

from app.config import settings
from app.logging import setup_logging

# Configure logging before anything else
setup_logging()

# Configure Redis broker
redis_broker = RedisBroker(url=settings.redis_url)  # type: ignore[no-untyped-call]
dramatiq.set_broker(redis_broker)
