"""SVG vectorization background task."""

import asyncio

import dramatiq
import structlog

from app.models.enums import SvgProcessingStatus
from app.services.coloring.vectorizer_service import VectorizerService
from app.services.external.mercure import MercureService
from app.services.external.vectorizer import (
    VectorizerApiService,
    VectorizerBadRequestError,
    VectorizerError,
)
from app.services.storage.paths import OrderStoragePaths
from app.services.storage.storage_service import S3StorageService
from app.tasks.decorators import task_recover
from app.tasks.utils.task_db import task_db_session

logger = structlog.get_logger(__name__)


@task_recover(VectorizerService.get_incomplete_versions)
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000, throws=VectorizerBadRequestError)
def generate_svg(svg_version_id: int) -> None:
    """Vectorize a coloring book to SVG.

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
    asyncio.run(_generate_svg_async(svg_version_id))


async def _generate_svg_async(svg_version_id: int) -> None:
    """Async implementation of SVG vectorization."""
    from app.models.coloring import ColoringVersion, SvgVersion
    from app.models.order import Image, LineItem, Order
    from app.tasks.utils.processing_lock import acquire_processing_lock

    mercure = MercureService()
    vectorizer = VectorizerApiService()
    storage = S3StorageService()

    logger.info("Starting SVG vectorization", svg_version_id=svg_version_id)

    async with task_db_session() as session:
        # Acquire exclusive lock with race condition protection
        lock_result = await acquire_processing_lock(
            session,
            SvgVersion,
            svg_version_id,
            completed_status=SvgProcessingStatus.COMPLETED,
        )
        if not lock_result.should_process:
            return

        svg_version = lock_result.record
        assert svg_version is not None  # Type narrowing

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

        # Load line item and order to get order_id
        line_item = await session.get(LineItem, image.line_item_id)
        if not line_item:
            logger.error("LineItem not found", line_item_id=image.line_item_id)
            svg_version.status = SvgProcessingStatus.ERROR
            await session.commit()
            return

        # Get order for Mercure and storage paths
        order = await session.get(Order, line_item.order_id)
        if not order:
            logger.error("Order not found", order_id=line_item.order_id)
            svg_version.status = SvgProcessingStatus.ERROR
            await session.commit()
            return

        assert order.id is not None
        order_id = order.id  # ULID string for Mercure

        # Publish initial PROCESSING status
        await mercure.publish_image_status(
            order_id=order_id,
            image_id=image_id,
            status_type="svg",
            version_id=svg_version_id,
            status=SvgProcessingStatus.PROCESSING,
        )

        async def update_status(new_status: SvgProcessingStatus) -> None:
            """Helper to update status in DB and publish to Mercure."""
            svg_version.status = new_status
            await session.commit()
            await mercure.publish_image_status(
                order_id=order_id,
                image_id=image_id,
                status_type="svg",
                version_id=svg_version_id,
                status=new_status,
            )

        try:
            # Verify source coloring image exists
            if not coloring_version.file_ref:
                raise FileNotFoundError("Coloring version has no file in S3")

            # Download input from S3
            image_data = await storage.download(coloring_version.file_ref)

            # Generate storage key for output using OrderStoragePaths
            paths = OrderStoragePaths(order)
            output_key = paths.svg_version(line_item, image, svg_version)

            # Update status: VECTORIZER_PROCESSING
            await update_status(SvgProcessingStatus.VECTORIZER_PROCESSING)

            # Process through Vectorizer (bytes in, bytes out)
            svg_data = await vectorizer.vectorize(
                image_data=image_data,
                filename=f"image_{image.position}.png",
                shape_stacking=svg_version.shape_stacking,
                group_by=svg_version.group_by,
            )

            # Upload result to S3
            file_ref = await storage.upload(
                upload_to=output_key,
                data=svg_data,
                content_type="image/svg+xml",
            )

            # Update version record
            svg_version.file_ref = file_ref
            svg_version.status = SvgProcessingStatus.COMPLETED

            # Set as selected SVG version for the image
            image.selected_svg_id = svg_version.id

            await session.commit()

            # Publish image_status for COMPLETED
            await mercure.publish_image_status(
                order_id=order_id,
                image_id=image_id,
                status_type="svg",
                version_id=svg_version_id,
                status=SvgProcessingStatus.COMPLETED,
            )

            logger.info(
                "SVG vectorization completed",
                svg_version_id=svg_version_id,
                s3_key=output_key,
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
            await mercure.publish_image_status(
                order_id=order_id,
                image_id=image_id,
                status_type="svg",
                version_id=svg_version_id,
                status=SvgProcessingStatus.ERROR,
            )
            # Re-raise so dramatiq can handle with throws parameter
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
            await mercure.publish_image_status(
                order_id=order_id,
                image_id=image_id,
                status_type="svg",
                version_id=svg_version_id,
                status=SvgProcessingStatus.ERROR,
            )
            raise
