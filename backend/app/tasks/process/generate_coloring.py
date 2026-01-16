"""Coloring book generation background task."""

import asyncio
from pathlib import Path

import anyio
import dramatiq
import structlog

from app.config import settings
from app.models.enums import ColoringProcessingStatus
from app.services.runpod import RunPodError, poll_job, submit_job
from app.tasks.image_download import task_db_session

logger = structlog.get_logger(__name__)


def _get_coloring_path(order_id: int, line_item_id: int, position: int, version: int) -> Path:
    """Generate storage path for a coloring version.

    Path format: <storage_path>/<order_id>/<line_item_id>/coloring/v<version>/image_<position>.png
    """
    base = Path(settings.storage_path)
    return base / str(order_id) / str(line_item_id) / "coloring" / f"v{version}" / f"image_{position}.png"


async def _generate_coloring_async(coloring_version_id: int) -> None:
    """Async implementation of coloring generation."""
    from app.models.coloring import ColoringVersion
    from app.models.order import Image, LineItem, Order
    from app.services.mercure import publish_image_status

    logger.info("Starting coloring generation", coloring_version_id=coloring_version_id)

    async with task_db_session() as session:
        # Load coloring version
        coloring_version = await session.get(ColoringVersion, coloring_version_id)
        if not coloring_version:
            logger.error("ColoringVersion not found", coloring_version_id=coloring_version_id)
            return

        # Set PROCESSING immediately (task has started)
        coloring_version.status = ColoringProcessingStatus.PROCESSING
        await session.commit()

        # Load the image
        image = await session.get(Image, coloring_version.image_id)
        if not image:
            logger.error("Image not found", image_id=coloring_version.image_id)
            coloring_version.status = ColoringProcessingStatus.ERROR
            await session.commit()
            return
        assert image.id is not None
        image_id = image.id  # Capture for closures

        # Load line item to get order_id
        line_item = await session.get(LineItem, image.line_item_id)
        if not line_item:
            logger.error("LineItem not found", line_item_id=image.line_item_id)
            coloring_version.status = ColoringProcessingStatus.ERROR
            await session.commit()
            return

        order_id = line_item.order_id

        # Get order number for Mercure
        order = await session.get(Order, order_id)
        order_number = order.clean_order_number if order else str(order_id)

        # Publish initial PROCESSING status
        await publish_image_status(
            order_number=order_number,
            image_id=image_id,
            status_type="coloring",
            version_id=coloring_version_id,
            status=ColoringProcessingStatus.PROCESSING,
        )

        async def update_status(new_status: ColoringProcessingStatus) -> None:
            """Helper to update status in DB and publish to Mercure."""
            coloring_version.status = new_status
            await session.commit()
            await publish_image_status(
                order_number=order_number,
                image_id=image_id,
                status_type="coloring",
                version_id=coloring_version_id,
                status=new_status,
            )

        try:
            # Verify source image exists
            if not image.local_path:
                raise FileNotFoundError("Image not downloaded yet")

            input_path = Path(image.local_path)
            if not input_path.exists():
                raise FileNotFoundError(f"Image file not found: {input_path}")

            # Generate output path
            output_path = _get_coloring_path(
                order_id=order_id,
                line_item_id=image.line_item_id,
                position=image.position,
                version=coloring_version.version,
            )

            # Read input image
            image_data = await anyio.Path(input_path).read_bytes()

            # Update status: RUNPOD_SUBMITTING
            await update_status(ColoringProcessingStatus.RUNPOD_SUBMITTING)

            # Submit to RunPod
            job_id = await submit_job(
                image_data=image_data,
                megapixels=coloring_version.megapixels,
                steps=coloring_version.steps,
            )

            # Update status: RUNPOD_SUBMITTED
            await update_status(ColoringProcessingStatus.RUNPOD_SUBMITTED)

            # Define callback for RunPod status changes
            async def on_runpod_status_change(runpod_status: str) -> None:
                """Handle RunPod status changes."""
                if runpod_status == "IN_QUEUE":
                    await update_status(ColoringProcessingStatus.RUNPOD_QUEUED)
                elif runpod_status == "IN_PROGRESS":
                    await update_status(ColoringProcessingStatus.RUNPOD_PROCESSING)

            # Poll for completion with status callbacks
            result_data = await poll_job(job_id, on_status_change=on_runpod_status_change)

            # Create output directory and save result (async)
            await anyio.Path(output_path.parent).mkdir(parents=True, exist_ok=True)
            await anyio.Path(output_path).write_bytes(result_data)

            # Update version record
            coloring_version.file_path = str(output_path)
            coloring_version.status = ColoringProcessingStatus.COMPLETED

            # Set as selected version for the image
            image.selected_coloring_id = coloring_version.id

            await session.commit()

            # Publish image_status for COMPLETED
            await publish_image_status(
                order_number=order_number,
                image_id=image_id,
                status_type="coloring",
                version_id=coloring_version_id,
                status=ColoringProcessingStatus.COMPLETED,
            )

            logger.info(
                "Coloring generation completed",
                coloring_version_id=coloring_version_id,
                output_path=str(output_path),
            )

        except (RunPodError, FileNotFoundError, OSError) as e:
            logger.error(
                "Coloring generation failed",
                coloring_version_id=coloring_version_id,
                error=str(e),
            )
            coloring_version.status = ColoringProcessingStatus.ERROR
            await session.commit()
            # Publish image_status for ERROR
            await publish_image_status(
                order_number=order_number,
                image_id=image_id,
                status_type="coloring",
                version_id=coloring_version_id,
                status=ColoringProcessingStatus.ERROR,
            )
            raise


@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def generate_coloring(coloring_version_id: int) -> None:
    """
    Generate a coloring book version for an image.

    This task:
    1. Sets status to PROCESSING immediately
    2. Loads the ColoringVersion and associated Image
    3. Submits to RunPod API (RUNPOD_SUBMITTING → RUNPOD_SUBMITTED)
    4. Polls for completion (RUNPOD_QUEUED → RUNPOD_PROCESSING)
    5. Saves output and updates status to COMPLETED
    6. Sets as selected coloring version for the image
    7. Publishes Mercure updates at each status change

    Args:
        coloring_version_id: ID of the ColoringVersion record to process
    """
    asyncio.run(_generate_coloring_async(coloring_version_id))
