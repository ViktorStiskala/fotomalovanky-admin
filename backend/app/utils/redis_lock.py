"""Redis-based distributed locking utilities."""

from collections.abc import Generator
from contextlib import contextmanager

from app.utils.redis import redis_client


class LockUnavailable(Exception):
    """Raised when lock cannot be acquired and raise_exc=True."""

    pass


@contextmanager
def RedisLock(
    key: str,
    ttl: int = 60,
    *,
    auto_release: bool = True,
    raise_exc: bool = False,
) -> Generator[None, None, None]:
    """Distributed lock using Redis SET NX with TTL.

    The with block ONLY executes if lock is acquired. If lock is not acquired,
    the block is skipped entirely (or raises if raise_exc=True).

    Basic usage (block skipped if lock not acquired):
        with RedisLock("my-lock", ttl=60):
            # This only runs if lock was acquired
            do_work()

    With explicit exception handling:
        try:
            with RedisLock("my-lock", ttl=60, raise_exc=True):
                do_work()
        except RedisLock.LockUnavailable:
            logger.debug("Lock not acquired, skipping")

    For deduplication (don't release on exit, let TTL expire):
        with RedisLock("task:123", ttl=300, auto_release=False):
            dispatch_task()

    Args:
        key: Redis key for the lock (will be prefixed with "RedisLock:")
        ttl: Time-to-live in seconds
        auto_release: If True, release lock on context exit. If False, let TTL expire.
        raise_exc: If True, raise LockUnavailable when lock not acquired.
    """
    full_key = f"RedisLock:{key}"
    acquired = bool(redis_client.set(full_key, "1", nx=True, ex=ttl))

    if not acquired:
        if raise_exc:
            raise LockUnavailable(f"Could not acquire lock: {full_key}")
        # Don't yield - block won't execute
        return

    try:
        yield
    finally:
        if auto_release:
            redis_client.delete(full_key)


# Attach exception to function for convenient access
RedisLock.LockUnavailable = LockUnavailable  # type: ignore[attr-defined]