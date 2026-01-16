"""Recovery module for tasks interrupted by worker restart.

This module finds tasks that were in intermediate processing states when
the worker was stopped/restarted and re-queues them for processing.
"""

import asyncio

import structlog

from app.db import async_session_maker
from app.tasks.decorators import get_recoverable_tasks

logger = structlog.get_logger(__name__)


async def _recover_stuck_tasks() -> int:
    """
    Find and re-queue tasks that were interrupted mid-processing.

    Uses the @task_recover decorator registry to discover tasks
    and their associated recovery functions.

    Returns:
        Total number of recovered tasks.
    """
    total_recovered = 0

    async with async_session_maker() as session:
        for task_fn, get_incomplete_fn in get_recoverable_tasks():
            try:
                version_ids = await get_incomplete_fn(session)
                for version_id in version_ids:
                    logger.info(
                        "Recovering stuck task",
                        task=task_fn.actor_name,
                        version_id=version_id,
                    )
                    task_fn.send(version_id)
                    total_recovered += 1
            except Exception as e:
                logger.error(
                    "Failed to recover tasks",
                    task=task_fn.actor_name,
                    error=str(e),
                )

    return total_recovered


def recover_stuck_tasks() -> None:
    """Synchronous wrapper for task recovery."""
    total_recovered = asyncio.run(_recover_stuck_tasks())

    if total_recovered > 0:
        logger.info(
            "Task recovery complete",
            tasks_recovered=total_recovered,
        )
    else:
        logger.debug("No stuck tasks found")
