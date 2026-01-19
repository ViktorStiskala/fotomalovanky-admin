"""SVG vectorization background task."""

import asyncio

import dramatiq
import structlog

from app.services.coloring.svg_generation_service import SvgGenerationService
from app.services.coloring.vectorizer_service import VectorizerService
from app.services.external.vectorizer import (
    VectorizerApiService,
    VectorizerBadRequestError,
    VectorizerError,
)
from app.services.mercure.publish_service import MercurePublishService
from app.services.storage.storage_service import S3StorageService
from app.tasks.decorators import task_recover
from app.tasks.utils.background_tasks import BackgroundTasks, background_tasks
from app.tasks.utils.processing_lock import RecordLockedError, RecordNotFoundError
from app.tasks.utils.task_db import task_db_session

logger = structlog.get_logger(__name__)


@task_recover(VectorizerService.get_incomplete_versions)
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000, throws=VectorizerBadRequestError)
def generate_svg(svg_version_id: int, *, is_recovery: bool = False) -> None:
    """Generate an SVG version from a coloring image."""
    # bg_tasks is injected by the @background_tasks decorator
    asyncio.run(_generate_svg_async(svg_version_id, is_recovery=is_recovery))  # type: ignore[call-arg, arg-type]


@background_tasks(timeout=30)
async def _generate_svg_async(
    svg_version_id: int,
    *,
    is_recovery: bool = False,
    bg_tasks: BackgroundTasks,  # Injected by @background_tasks decorator
) -> None:
    """Async implementation - decorator handles bg_tasks injection and cleanup."""
    mercure = MercurePublishService()
    vectorizer = VectorizerApiService()
    storage = S3StorageService()

    logger.info(
        "Starting SVG generation",
        svg_version_id=svg_version_id,
        is_recovery=is_recovery,
    )

    async with task_db_session() as session:
        service = SvgGenerationService(
            session=session,
            storage=storage,
            vectorizer=vectorizer,
            mercure_service=mercure,
            bg_tasks=bg_tasks,
        )

        try:
            await service.process(svg_version_id, is_recovery=is_recovery)

        except RecordNotFoundError as e:
            logger.error(str(e), svg_version_id=svg_version_id)
            return

        except RecordLockedError as e:
            logger.info(str(e), svg_version_id=svg_version_id)
            return

        except VectorizerBadRequestError as e:
            # Bad request - don't retry, just mark as error
            logger.error(
                "SVG vectorization failed (bad request)",
                svg_version_id=svg_version_id,
                error=str(e),
            )
            await service.mark_error(svg_version_id)
            # Re-raise so dramatiq can handle with throws parameter
            raise

        except (VectorizerError, FileNotFoundError, OSError) as e:
            logger.error(
                "SVG generation failed",
                svg_version_id=svg_version_id,
                error=str(e),
            )
            await service.mark_error(svg_version_id)
            raise
