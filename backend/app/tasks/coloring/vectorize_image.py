"""SVG vectorization background task."""

import asyncio

import dramatiq
import structlog

from app.services.coloring.svg_generation_service import SvgGenerationService
from app.services.coloring.vectorizer_service import VectorizerService
from app.services.external.vectorizer import VectorizerApiService, VectorizerBadRequestError
from app.services.storage.storage_service import S3StorageService
from app.tasks.decorators import task_recover
from app.tasks.utils.background_tasks import BackgroundTasks, background_tasks
from app.tasks.utils.task_db import task_db_session

logger = structlog.get_logger(__name__)


@task_recover(VectorizerService.get_incomplete_versions)
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000, throws=VectorizerBadRequestError)
def generate_svg(
    svg_version_id: int,
    *,
    order_id: str,
    image_id: int,
    is_recovery: bool = False,
) -> None:
    """Generate an SVG version from a coloring image.

    Args:
        svg_version_id: ID of the SvgVersion to process
        order_id: Order ULID for Mercure context
        image_id: Image ID for Mercure context
        is_recovery: True if called from recovery.py (affects expected states)
    """
    # bg_tasks is injected by the @background_tasks decorator
    asyncio.run(
        _generate_svg_async(  # type: ignore[arg-type]
            svg_version_id,
            order_id=order_id,
            image_id=image_id,
            is_recovery=is_recovery,
        )  # type: ignore[call-arg]
    )


@background_tasks(timeout=30)
async def _generate_svg_async(
    svg_version_id: int,
    *,
    order_id: str,
    image_id: int,
    is_recovery: bool = False,
    bg_tasks: BackgroundTasks,  # Injected by @background_tasks decorator
) -> None:
    """Async implementation - decorator handles bg_tasks injection and cleanup."""
    vectorizer = VectorizerApiService()
    storage = S3StorageService()

    logger.info(
        "Starting SVG generation",
        svg_version_id=svg_version_id,
        order_id=order_id,
        image_id=image_id,
        is_recovery=is_recovery,
    )

    async with task_db_session(bg_tasks=bg_tasks) as session:
        service = SvgGenerationService(
            session=session,
            storage=storage,
            vectorizer=vectorizer,
        )

        # Service handles errors internally via _mark_error()
        # Exceptions propagate for dramatiq retry handling
        await service.process(
            svg_version_id,
            order_id=order_id,
            image_id=image_id,
            is_recovery=is_recovery,
        )
