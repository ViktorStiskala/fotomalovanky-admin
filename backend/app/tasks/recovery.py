"""Recovery module for tasks interrupted by worker restart.

This module finds tasks that were in intermediate processing states when
the worker was stopped/restarted and re-queues them for processing.
"""

import asyncio

import structlog
from sqlmodel import select

from app.db import async_session_maker
from app.models.coloring import ColoringVersion, SvgVersion
from app.models.enums import ColoringProcessingStatus, SvgProcessingStatus

logger = structlog.get_logger(__name__)

# Intermediate states that indicate a task was interrupted
COLORING_INTERMEDIATE_STATES = {
    ColoringProcessingStatus.PROCESSING,
    ColoringProcessingStatus.RUNPOD_SUBMITTING,
    ColoringProcessingStatus.RUNPOD_SUBMITTED,
    ColoringProcessingStatus.RUNPOD_QUEUED,
    ColoringProcessingStatus.RUNPOD_PROCESSING,
}

SVG_INTERMEDIATE_STATES = {
    SvgProcessingStatus.PROCESSING,
    SvgProcessingStatus.VECTORIZER_PROCESSING,
}


async def _recover_stuck_tasks() -> tuple[int, int]:
    """
    Find and re-queue tasks that were interrupted mid-processing.

    Returns:
        Tuple of (coloring_count, svg_count) recovered tasks.
    """
    from app.tasks import generate_coloring, vectorize_image

    coloring_count = 0
    svg_count = 0

    async with async_session_maker() as session:
        # Find stuck coloring versions
        coloring_stmt = select(ColoringVersion).where(
            ColoringVersion.status.in_(COLORING_INTERMEDIATE_STATES)  # type: ignore[attr-defined]
        )
        coloring_result = await session.execute(coloring_stmt)
        stuck_colorings = coloring_result.scalars().all()

        for cv in stuck_colorings:
            logger.info(
                "Recovering stuck coloring task",
                coloring_version_id=cv.id,
                previous_status=cv.status,
            )
            cv.status = ColoringProcessingStatus.QUEUED
            coloring_count += 1

        # Find stuck SVG versions
        svg_stmt = select(SvgVersion).where(
            SvgVersion.status.in_(SVG_INTERMEDIATE_STATES)  # type: ignore[attr-defined]
        )
        svg_result = await session.execute(svg_stmt)
        stuck_svgs = svg_result.scalars().all()

        for sv in stuck_svgs:
            logger.info(
                "Recovering stuck SVG task",
                svg_version_id=sv.id,
                previous_status=sv.status,
            )
            sv.status = SvgProcessingStatus.QUEUED
            svg_count += 1

        await session.commit()

        # Re-dispatch tasks after commit
        for cv in stuck_colorings:
            assert cv.id is not None
            generate_coloring.send(cv.id)

        for sv in stuck_svgs:
            assert sv.id is not None
            vectorize_image.send(sv.id)

    return coloring_count, svg_count


def recover_stuck_tasks() -> None:
    """Synchronous wrapper for task recovery."""
    coloring_count, svg_count = asyncio.run(_recover_stuck_tasks())

    if coloring_count > 0 or svg_count > 0:
        logger.info(
            "Task recovery complete",
            coloring_tasks_recovered=coloring_count,
            svg_tasks_recovered=svg_count,
        )
    else:
        logger.debug("No stuck tasks found")
