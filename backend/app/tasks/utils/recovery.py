"""Recovery module for tasks interrupted by worker restart.

This module finds tasks that were in intermediate processing states when
the worker was stopped/restarted and re-queues them for processing.
"""

import asyncio

import dramatiq
import structlog

from app.db import async_session_maker
from app.tasks.utils.decorators import get_recoverable_tasks
from app.utils.redis_lock import LockUnavailable, RedisLock

logger = structlog.get_logger(__name__)

# Lock settings
RECOVERY_TASK_LOCK_TTL = 300  # 5 minutes
RECOVERY_DISPATCH_TTL = 300  # 5 minutes per task


@dramatiq.actor(max_retries=0, queue_name="default")
def run_recovery() -> None:
    """Dramatiq task to recover stuck tasks.

    Uses Redis lock to ensure only one recovery runs at a time,
    even across container restarts.
    """
    try:
        with RedisLock("dramatiq:recovery:task", ttl=RECOVERY_TASK_LOCK_TTL, raise_exc=True):
            total = asyncio.run(_recover_stuck_tasks())
            if total > 0:
                logger.info("Task recovery complete", tasks_recovered=total)
            else:
                logger.debug("No stuck tasks found")
    except LockUnavailable:
        logger.debug("Recovery task already running, skipping")


async def _recover_stuck_tasks() -> int:
    """Find and re-queue tasks with deduplication.

    Uses the @task_recover decorator registry to discover tasks
    and their associated recovery functions.

    The recovery functions return dicts with version_id, order_id, and image_id
    which are passed to the task for proper Mercure context.

    Returns:
        Total number of recovered tasks.
    """
    total_recovered = 0

    async with async_session_maker() as session:
        for task_fn, get_incomplete_fn in get_recoverable_tasks():
            try:
                # get_incomplete_fn returns list of dicts with version_id, order_id, image_id
                items = await get_incomplete_fn(session)
                for item in items:
                    # Deduplicate: skip if already dispatched recently
                    # auto_release=False means lock stays until TTL expires (deduplication pattern)
                    with RedisLock(
                        f"recovery:{task_fn.actor_name}:{item['version_id']}",
                        ttl=RECOVERY_DISPATCH_TTL,
                        auto_release=False,
                    ):
                        logger.info(
                            "Recovering stuck task",
                            task=task_fn.actor_name,
                            version_id=item["version_id"],
                            order_id=item["order_id"],
                            image_id=item["image_id"],
                        )
                        # Pass context for Mercure auto-tracking
                        task_fn.send(
                            item["version_id"],
                            order_id=item["order_id"],
                            image_id=item["image_id"],
                            is_recovery=True,
                        )
                        total_recovered += 1
            except Exception as e:
                logger.error(
                    "Failed to recover tasks",
                    task=task_fn.actor_name,
                    error=str(e),
                )

    return total_recovered
