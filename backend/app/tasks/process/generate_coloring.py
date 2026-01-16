"""Coloring book generation background task."""

import asyncio
from pathlib import Path

import dramatiq
import structlog

from app.config import settings
from app.models.enums import ImageProcessingStatus
from app.services.runpod import RunPodError, process_image
from app.tasks.image_download import task_db_session

logger = structlog.get_logger(__name__)


def _get_coloring_path(order_id: int, line_item_id: int, image_id: int, version: int) -> Path:
    """Generate storage path for a coloring version."""
    base = Path(settings.storage_path)
    return base / str(order_id) / str(line_item_id) / f"image_{image_id}_coloring_v{version}.png"


async def _generate_coloring_async(coloring_version_id: int) -> None:
    """Async implementation of coloring generation."""
    from app.models.coloring import ColoringVersion
    from app.models.order import Image, LineItem
    from app.services.mercure import publish_order_update

    logger.info("Starting coloring generation", coloring_version_id=coloring_version_id)

    async with task_db_session() as session:
        # Load coloring version with image
        coloring_version = await session.get(ColoringVersion, coloring_version_id)
        if not coloring_version:
            logger.error("ColoringVersion not found", coloring_version_id=coloring_version_id)
            return

        # Load the image
        image = await session.get(Image, coloring_version.image_id)
        if not image:
            logger.error("Image not found", image_id=coloring_version.image_id)
            coloring_version.status = ImageProcessingStatus.ERROR
            await session.commit()
            return
        assert image.id is not None

        # Load line item to get order_id
        line_item = await session.get(LineItem, image.line_item_id)
        if not line_item:
            logger.error("LineItem not found", line_item_id=image.line_item_id)
            coloring_version.status = ImageProcessingStatus.ERROR
            await session.commit()
            return

        order_id = line_item.order_id

        # Get order number for Mercure
        from app.models.order import Order

        order = await session.get(Order, order_id)
        order_number = order.shopify_order_number.lstrip("#") if order else str(order_id)

        try:
            # Update status to PROCESSING
            coloring_version.status = ImageProcessingStatus.PROCESSING
            await session.commit()
            await publish_order_update(order_number)

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
                image_id=image.id,
                version=coloring_version.version,
            )

            # Process through RunPod
            await process_image(
                input_path=input_path,
                output_path=output_path,
                megapixels=coloring_version.megapixels,
                steps=coloring_version.steps,
            )

            # Update version record
            coloring_version.file_path = str(output_path)
            coloring_version.status = ImageProcessingStatus.COMPLETED

            # Set as selected version for the image
            image.selected_coloring_id = coloring_version.id

            await session.commit()
            await publish_order_update(order_number)

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
            coloring_version.status = ImageProcessingStatus.ERROR
            await session.commit()
            await publish_order_update(order_number)
            raise


@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def generate_coloring(coloring_version_id: int) -> None:
    """
    Generate a coloring book version for an image.

    This task:
    1. Loads the ColoringVersion and associated Image
    2. Sets status to PROCESSING
    3. Processes image through RunPod API
    4. Saves output and updates status to COMPLETED
    5. Sets as selected coloring version for the image
    6. Publishes Mercure update

    Args:
        coloring_version_id: ID of the ColoringVersion record to process
    """
    asyncio.run(_generate_coloring_async(coloring_version_id))
