"""Coloring book generation background task."""

import asyncio

import dramatiq
import structlog

from app.services.coloring.coloring_generation_service import ColoringGenerationService
from app.services.coloring.coloring_service import ColoringService
from app.services.external.runpod import RunPodService
from app.services.storage.storage_service import S3StorageService
from app.tasks.utils.background_tasks import BackgroundTasks, background_tasks
from app.tasks.utils.decorators import task_recover
from app.tasks.utils.task_db import task_db_session

logger = structlog.get_logger(__name__)


@task_recover(ColoringService.get_incomplete_versions)
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def generate_coloring(
    coloring_version_id: int,
    *,
    order_id: str,
    image_id: int,
    is_recovery: bool = False,
) -> None:
    """Generate a coloring book version for an image.

    Args:
        coloring_version_id: ID of the ColoringVersion to process
        order_id: Order ULID for Mercure context
        image_id: Image ID for Mercure context
        is_recovery: True if called from recovery.py (affects expected states)
    """
    # bg_tasks is injected by the @background_tasks decorator
    asyncio.run(
        _generate_coloring_async(  # type: ignore[arg-type]
            coloring_version_id,
            order_id=order_id,
            image_id=image_id,
            is_recovery=is_recovery,
        )  # type: ignore[call-arg]
    )


@background_tasks(timeout=30)
async def _generate_coloring_async(
    coloring_version_id: int,
    *,
    order_id: str,
    image_id: int,
    is_recovery: bool = False,
    bg_tasks: BackgroundTasks,  # Injected by @background_tasks decorator
) -> None:
    """Async implementation - decorator handles bg_tasks injection and cleanup."""
    runpod = RunPodService()
    storage = S3StorageService()

    logger.info(
        "Starting coloring generation",
        coloring_version_id=coloring_version_id,
        order_id=order_id,
        image_id=image_id,
        is_recovery=is_recovery,
    )

    async with task_db_session(bg_tasks=bg_tasks) as session:
        service = ColoringGenerationService(
            session=session,
            storage=storage,
            runpod=runpod,
        )

        # Service handles errors internally via _mark_error()
        # Exceptions propagate for dramatiq retry handling
        await service.process(
            coloring_version_id,
            order_id=order_id,
            image_id=image_id,
            is_recovery=is_recovery,
        )
