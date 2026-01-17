"""Coloring book generation background task."""

import asyncio

import dramatiq
import structlog

from app.models.enums import ColoringProcessingStatus
from app.services.coloring.coloring_service import ColoringService
from app.services.external.mercure import MercureService
from app.services.external.runpod import RunPodError, RunPodService
from app.services.storage.storage_service import LocalStorageService, StorageService
from app.tasks.decorators import task_recover
from app.tasks.utils import task_db_session

logger = structlog.get_logger(__name__)


@task_recover(ColoringService.get_incomplete_versions)
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def generate_coloring(coloring_version_id: int) -> None:
    """Generate a coloring book version for an image.

    This task:
    1. Sets status to PROCESSING immediately
    2. Loads the ColoringVersion and associated Image
    3. Submits to RunPod API (RUNPOD_SUBMITTING -> RUNPOD_SUBMITTED)
    4. Polls for completion (RUNPOD_QUEUED -> RUNPOD_PROCESSING)
    5. Saves output and updates status to COMPLETED
    6. Sets as selected coloring version for the image
    7. Publishes Mercure updates at each status change

    Args:
        coloring_version_id: ID of the ColoringVersion record to process
    """
    asyncio.run(_generate_coloring_async(coloring_version_id))


async def _generate_coloring_async(coloring_version_id: int) -> None:
    """Async implementation of coloring generation."""
    from app.models.coloring import ColoringVersion
    from app.models.order import Image, LineItem, Order

    mercure = MercureService()
    runpod = RunPodService()
    storage: StorageService = LocalStorageService()

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
        await mercure.publish_image_status(
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
            await mercure.publish_image_status(
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

            # Read input image using storage service
            if not await storage.exists_by_path(image.local_path):
                raise FileNotFoundError(f"Image file not found: {image.local_path}")

            image_data = await storage.read_by_path(image.local_path)

            # Generate storage key for output
            output_key = storage.get_coloring_key(
                order_id=order_id,
                line_item_id=image.line_item_id,
                position=image.position,
                version=coloring_version.version,
            )

            # Update status: RUNPOD_SUBMITTING
            await update_status(ColoringProcessingStatus.RUNPOD_SUBMITTING)

            # Submit to RunPod
            job_id = await runpod.submit_job(
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
            result_data = await runpod.poll_job(job_id, on_status_change=on_runpod_status_change)

            # Save result using storage service
            output_path = await storage.write(output_key, result_data)

            # Update version record
            coloring_version.file_path = output_path
            coloring_version.status = ColoringProcessingStatus.COMPLETED

            # Set as selected version for the image
            image.selected_coloring_id = coloring_version.id

            await session.commit()

            # Publish image_status for COMPLETED
            await mercure.publish_image_status(
                order_number=order_number,
                image_id=image_id,
                status_type="coloring",
                version_id=coloring_version_id,
                status=ColoringProcessingStatus.COMPLETED,
            )

            logger.info(
                "Coloring generation completed",
                coloring_version_id=coloring_version_id,
                output_path=output_path,
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
            await mercure.publish_image_status(
                order_number=order_number,
                image_id=image_id,
                status_type="coloring",
                version_id=coloring_version_id,
                status=ColoringProcessingStatus.ERROR,
            )
            raise
