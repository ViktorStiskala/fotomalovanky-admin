"""Shared HTTP request retry utilities using tenacity."""

from dataclasses import dataclass

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)


@dataclass
class RequestRetryConfig:
    """Configuration for HTTP request retries with exponential backoff."""

    max_attempts: int = 3
    min_wait: float = 1.0
    max_wait: float = 10.0
    multiplier: float = 1.0


def get_request_retrying(config: RequestRetryConfig | None = None) -> AsyncRetrying:
    """Get configured AsyncRetrying for httpx.RequestError (network errors).

    Usage:
        async for attempt in get_request_retrying():
            with attempt:
                response = await client.get(url)

    Args:
        config: Optional retry configuration. Uses defaults if not provided.

    Returns:
        AsyncRetrying instance configured for httpx.RequestError retries.
    """
    cfg = config or RequestRetryConfig()
    return AsyncRetrying(
        retry=retry_if_exception_type(httpx.RequestError),
        stop=stop_after_attempt(cfg.max_attempts),
        wait=wait_exponential(
            multiplier=cfg.multiplier,
            min=cfg.min_wait,
            max=cfg.max_wait,
        ),
        reraise=True,
    )
