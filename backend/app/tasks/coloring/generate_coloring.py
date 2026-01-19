"""Coloring book generation background task."""

import asyncio

import dramatiq
import structlog

from app.services.coloring.coloring_generation_service import ColoringGenerationService
from app.services.coloring.coloring_service import ColoringService
from app.services.external.runpod import RunPodError, RunPodService
from app.services.mercure.publish_service import MercurePublishService
from app.services.storage.storage_service import S3StorageService
from app.tasks.decorators import task_recover
from app.tasks.utils.background_tasks import BackgroundTasks, background_tasks
from app.tasks.utils.processing_lock import RecordLockedError, RecordNotFoundError
from app.tasks.utils.task_db import task_db_session

logger = structlog.get_logger(__name__)


@task_recover(ColoringService.get_incomplete_versions)
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def generate_coloring(coloring_version_id: int, *, is_recovery: bool = False) -> None:
    """Generate a coloring book version for an image."""
    # bg_tasks is injected by the @background_tasks decorator
    asyncio.run(_generate_coloring_async(coloring_version_id, is_recovery=is_recovery))  # type: ignore[call-arg, arg-type]


@background_tasks(timeout=30)
async def _generate_coloring_async(
    coloring_version_id: int,
    *,
    is_recovery: bool = False,
    bg_tasks: BackgroundTasks,  # Injected by @background_tasks decorator
) -> None:
    """Async implementation - decorator handles bg_tasks injection and cleanup."""
    mercure = MercurePublishService()
    runpod = RunPodService()
    storage = S3StorageService()

    logger.info(
        "Starting coloring generation",
        coloring_version_id=coloring_version_id,
        is_recovery=is_recovery,
    )

    async with task_db_session() as session:
        service = ColoringGenerationService(
            session=session,
            storage=storage,
            runpod=runpod,
            mercure_service=mercure,
            bg_tasks=bg_tasks,
        )

        try:
            await service.process(coloring_version_id, is_recovery=is_recovery)

        except RecordNotFoundError as e:
            logger.error(str(e), coloring_version_id=coloring_version_id)
            return

        except RecordLockedError as e:
            logger.info(str(e), coloring_version_id=coloring_version_id)
            return

        except (RunPodError, FileNotFoundError, OSError) as e:
            logger.error(
                "Coloring generation failed",
                coloring_version_id=coloring_version_id,
                error=str(e),
            )
            await service.mark_error(coloring_version_id)
            raise
