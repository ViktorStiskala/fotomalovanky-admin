"""Shared Redis client."""

import redis

from app.config import settings

# Shared Redis client - reuse across all utilities
redis_client: redis.Redis = redis.from_url(settings.redis_url)  # type: ignore[no-untyped-call]
