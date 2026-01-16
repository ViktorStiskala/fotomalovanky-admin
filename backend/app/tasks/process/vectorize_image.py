"""SVG vectorization background task."""

import asyncio
from pathlib import Path

import dramatiq
import structlog

from app.config import settings
from app.models.enums import SvgProcessingStatus
from app.services.vectorizer import VectorizerBadRequestError, VectorizerError
from app.services.vectorizer import vectorize_image as vectorize_service
from app.tasks.image_download import task_db_session

logger = structlog.get_logger(__name__)


def _get_svg_path(order_id: int, line_item_id: int, position: int, version: int) -> Path:
    """Generate storage path for an SVG version.

    Path format: <storage_path>/<order_id>/<line_item_id>/svg/v<version>/image_<position>.svg
    """
    base = Path(settings.storage_path)
    return base / str(order_id) / str(line_item_id) / "svg" / f"v{version}" / f"image_{position}.svg"


async def _vectorize_image_async(svg_version_id: int) -> None:
    """Async implementation of SVG vectorization."""
    from app.models.coloring import ColoringVersion, SvgVersion
    from app.models.order import Image, LineItem, Order
    from app.services.mercure import publish_image_status

    logger.info("Starting SVG vectorization", svg_version_id=svg_version_id)

    async with task_db_session() as session:
        # Load SVG version
        svg_version = await session.get(SvgVersion, svg_version_id)
        if not svg_version:
            logger.error("SvgVersion not found", svg_version_id=svg_version_id)
            return

        # Set PROCESSING immediately (task has started)
        svg_version.status = SvgProcessingStatus.PROCESSING
        await session.commit()

        # Load the coloring version
        coloring_version = await session.get(ColoringVersion, svg_version.coloring_version_id)
        if not coloring_version:
            logger.error(
                "ColoringVersion not found",
                coloring_version_id=svg_version.coloring_version_id,
            )
            svg_version.status = SvgProcessingStatus.ERROR
            await session.commit()
            return

        # Load the image
        image = await session.get(Image, coloring_version.image_id)
        if not image:
            logger.error("Image not found", image_id=coloring_version.image_id)
            svg_version.status = SvgProcessingStatus.ERROR
            await session.commit()
            return
        assert image.id is not None
        image_id = image.id  # Capture for closures

        # Load line item to get order_id
        line_item = await session.get(LineItem, image.line_item_id)
        if not line_item:
            logger.error("LineItem not found", line_item_id=image.line_item_id)
            svg_version.status = SvgProcessingStatus.ERROR
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
            status_type="svg",
            version_id=svg_version_id,
            status=SvgProcessingStatus.PROCESSING,
        )

        async def update_status(new_status: SvgProcessingStatus) -> None:
            """Helper to update status in DB and publish to Mercure."""
            svg_version.status = new_status
            await session.commit()
            await publish_image_status(
                order_number=order_number,
                image_id=image_id,
                status_type="svg",
                version_id=svg_version_id,
                status=new_status,
            )

        try:
            # Verify source coloring image exists
            if not coloring_version.file_path:
                raise FileNotFoundError("Coloring version has no file")

            input_path = Path(coloring_version.file_path)
            if not input_path.exists():
                raise FileNotFoundError(f"Coloring file not found: {input_path}")

            # Generate output path
            output_path = _get_svg_path(
                order_id=order_id,
                line_item_id=image.line_item_id,
                position=image.position,
                version=svg_version.version,
            )

            # Update status: VECTORIZER_PROCESSING
            await update_status(SvgProcessingStatus.VECTORIZER_PROCESSING)

            # Process through Vectorizer
            await vectorize_service(
                input_path=input_path,
                output_path=output_path,
                shape_stacking=svg_version.shape_stacking,
                group_by=svg_version.group_by,
            )

            # Update version record
            svg_version.file_path = str(output_path)
            svg_version.status = SvgProcessingStatus.COMPLETED

            # Set as selected SVG version for the image
            image.selected_svg_id = svg_version.id

            await session.commit()

            # Publish image_status for COMPLETED
            await publish_image_status(
                order_number=order_number,
                image_id=image_id,
                status_type="svg",
                version_id=svg_version_id,
                status=SvgProcessingStatus.COMPLETED,
            )

            logger.info(
                "SVG vectorization completed",
                svg_version_id=svg_version_id,
                output_path=str(output_path),
            )

        except VectorizerBadRequestError as e:
            # Bad request - don't retry, just mark as error
            logger.error(
                "SVG vectorization failed (bad request)",
                svg_version_id=svg_version_id,
                error=str(e),
            )
            svg_version.status = SvgProcessingStatus.ERROR
            await session.commit()
            # Publish image_status for ERROR
            await publish_image_status(
                order_number=order_number,
                image_id=image_id,
                status_type="svg",
                version_id=svg_version_id,
                status=SvgProcessingStatus.ERROR,
            )
            # Don't re-raise - the throws parameter will prevent retries
            raise

        except (VectorizerError, FileNotFoundError, OSError) as e:
            logger.error(
                "SVG vectorization failed",
                svg_version_id=svg_version_id,
                error=str(e),
            )
            svg_version.status = SvgProcessingStatus.ERROR
            await session.commit()
            # Publish image_status for ERROR
            await publish_image_status(
                order_number=order_number,
                image_id=image_id,
                status_type="svg",
                version_id=svg_version_id,
                status=SvgProcessingStatus.ERROR,
            )
            raise


@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000, throws=VectorizerBadRequestError)
def vectorize_image(svg_version_id: int) -> None:
    """
    Vectorize a coloring book to SVG.

    This task:
    1. Sets status to PROCESSING immediately
    2. Loads the SvgVersion and associated ColoringVersion
    3. Sets status to VECTORIZER_PROCESSING before HTTP request
    4. Processes coloring PNG through Vectorizer.ai API
    5. Saves output and updates status to COMPLETED
    6. Sets as selected SVG version for the image
    7. Publishes Mercure updates at each status change

    Args:
        svg_version_id: ID of the SvgVersion record to process
    """
    asyncio.run(_vectorize_image_async(svg_version_id))
