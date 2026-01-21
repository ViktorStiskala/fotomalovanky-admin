"""SVG vectorization processing service.

Handles Vectorizer.ai processing and S3 upload with:
- Short-lived database locks (only during state transitions)
- State verification before each transition
- Automatic Mercure event publishing via TrackedAsyncSession
- Recovery support
"""

from datetime import UTC, datetime

import structlog

from app.db.mercure_protocol import mercure_autotrack
from app.db.processing_lock import ProcessingLock, RecordLockedError, RecordNotFoundError
from app.db.tracked_session import TrackedAsyncSession
from app.models.coloring import ColoringVersion, SvgVersion
from app.models.enums import SvgProcessingStatus
from app.models.order import Image, LineItem, Order
from app.services.exceptions import UnexpectedStatusError
from app.services.external.vectorizer import (
    VectorizerApiService,
    VectorizerBadRequestError,
    VectorizerError,
)
from app.services.mercure.events import ImageUpdateEvent
from app.services.storage.paths import OrderStoragePaths
from app.services.storage.storage_service import S3StorageService

logger = structlog.get_logger(__name__)


@mercure_autotrack(ImageUpdateEvent)
class SvgGenerationService:
    """Service for processing SVG vectorization via Vectorizer.ai.

    Mercure events are published automatically via TrackedAsyncSession
    when status fields change.
    """

    session: TrackedAsyncSession  # Required by MercureTrackable protocol

    def __init__(
        self,
        session: TrackedAsyncSession,
        storage: S3StorageService,
        vectorizer: VectorizerApiService,
    ):
        self.session = session
        self.storage = storage
        self.vectorizer = vectorizer

    async def process(
        self,
        svg_version_id: int,
        *,
        order_id: str,
        image_id: int,
        is_recovery: bool = False,
    ) -> None:
        """Process an SVG version.

        Args:
            svg_version_id: ID of the SvgVersion to process
            order_id: Order ULID for Mercure context
            image_id: Image ID for Mercure context
            is_recovery: True if called from recovery.py (affects expected states)
        """
        # MUST be first line - sets context for Mercure event publishing
        self.session.set_mercure_context(Order.id == order_id, Image.id == image_id)  # type: ignore[arg-type]

        try:
            await self._process_impl(svg_version_id, is_recovery=is_recovery)
        except VectorizerBadRequestError as e:
            # Bad request - don't retry, just mark as error
            logger.error(
                "SVG vectorization failed (bad request)",
                svg_version_id=svg_version_id,
                error=str(e),
            )
            await self._mark_error(svg_version_id)
            raise
        except (VectorizerError, FileNotFoundError, OSError) as e:
            logger.error(
                "SVG generation failed",
                svg_version_id=svg_version_id,
                error=str(e),
            )
            await self._mark_error(svg_version_id)
            raise
        except RecordNotFoundError as e:
            logger.error(str(e), svg_version_id=svg_version_id)
            return
        except RecordLockedError as e:
            logger.info(str(e), svg_version_id=svg_version_id)
            return

    async def _process_impl(self, svg_version_id: int, *, is_recovery: bool = False) -> None:
        """Internal implementation of SVG processing."""
        locker = ProcessingLock(
            self.session,
            SvgVersion,
            SvgVersion.id == svg_version_id,  # type: ignore[arg-type]
        )

        # === LOCK 1: Check preconditions and mark as PROCESSING ===
        async with locker.acquire() as lock:
            version = lock.record
            assert version is not None

            if is_recovery:
                logger.warning(
                    "Recovering SVG task",
                    version_id=version.id,
                    status=version.status.value,
                    has_file_ref=version.file_ref is not None,
                )

            if version.file_ref is not None:
                logger.warning("SvgVersion already has file_ref", version_id=version.id)
                await lock.update_record(status=SvgProcessingStatus.COMPLETED)
                return

            if is_recovery:
                allowed = version.status.meta.is_recoverable or version.status.meta.is_startable
            else:
                allowed = version.status.meta.is_startable or version.status.meta.is_retryable

            if not allowed:
                logger.warning(
                    "SvgVersion not in processable state",
                    version_id=version.id,
                    status=version.status.value,
                    is_recovery=is_recovery,
                )
                return

            # Capture values needed outside lock
            image_id = version.image_id
            coloring_version_id = version.coloring_version_id
            shape_stacking = version.shape_stacking
            group_by = version.group_by
            current_status = version.status

            if current_status in {SvgProcessingStatus.PENDING, SvgProcessingStatus.QUEUED}:
                await lock.update_record(
                    status=SvgProcessingStatus.PROCESSING,
                    started_at=datetime.now(UTC),
                )

        # === OUTSIDE LOCK: Load related objects ===
        image = await self.session.get(Image, image_id)
        if not image:
            raise ValueError(f"Image {image_id} not found")

        coloring_version = await self.session.get(ColoringVersion, coloring_version_id)
        if not coloring_version:
            raise ValueError(f"ColoringVersion {coloring_version_id} not found")

        line_item = await self.session.get(LineItem, image.line_item_id)
        if not line_item:
            raise ValueError(f"LineItem {image.line_item_id} not found")

        order = await self.session.get(Order, line_item.order_id)
        if not order:
            raise ValueError(f"Order {line_item.order_id} not found")

        # Use the coloring_version we loaded (linked by coloring_version_id)
        if not coloring_version.file_ref:
            raise FileNotFoundError("Coloring version has no file in S3")

        # === OUTSIDE LOCK: Download coloring ===
        image_data = await self.storage.download(coloring_version.file_ref)

        # === LOCK 2: Verify PROCESSING and mark VECTORIZER_PROCESSING ===
        async with locker.acquire() as lock:
            try:
                await lock.verify_and_update_status(
                    expected=SvgProcessingStatus.PROCESSING,
                    new_status=SvgProcessingStatus.VECTORIZER_PROCESSING,
                )
            except UnexpectedStatusError as e:
                logger.error("Cannot start vectorization", version_id=svg_version_id, actual=e.actual.value)
                return

        # === OUTSIDE LOCK: Vectorize (long-running) ===
        svg_data = await self.vectorizer.vectorize(
            image_data=image_data,
            filename=f"image_{image.position}.png",
            shape_stacking=shape_stacking,
            group_by=group_by,
        )

        # === LOCK 3: Mark VECTORIZER_COMPLETED ===
        async with locker.acquire() as lock:
            try:
                await lock.verify_and_update_status(
                    expected=SvgProcessingStatus.VECTORIZER_PROCESSING,
                    new_status=SvgProcessingStatus.VECTORIZER_COMPLETED,
                )
            except UnexpectedStatusError as e:
                logger.error("Cannot mark VECTORIZER_COMPLETED", version_id=svg_version_id, actual=e.actual.value)
                return

        # === LOCK 4: Mark STORAGE_UPLOAD ===
        async with locker.acquire() as lock:
            try:
                await lock.verify_and_update_status(
                    expected=SvgProcessingStatus.VECTORIZER_COMPLETED,
                    new_status=SvgProcessingStatus.STORAGE_UPLOAD,
                )
            except UnexpectedStatusError as e:
                logger.error("Cannot start upload", version_id=svg_version_id, actual=e.actual.value)
                return

        # === OUTSIDE LOCK: Upload to S3 ===
        # Reload version to get the version object for path generation
        version_for_path = await self.session.get(SvgVersion, svg_version_id)
        assert version_for_path is not None

        paths = OrderStoragePaths(order)
        output_key = paths.svg_version(line_item, image, version_for_path)

        file_ref = await self.storage.upload(
            upload_to=output_key,
            data=svg_data,
            content_type="image/svg+xml",
        )

        # === LOCK 5: Mark COMPLETED ===
        async with locker.acquire() as lock:
            try:
                await lock.verify_and_update_status(
                    expected=SvgProcessingStatus.STORAGE_UPLOAD,
                    new_status=SvgProcessingStatus.COMPLETED,
                    file_ref=file_ref,
                    completed_at=datetime.now(UTC),
                )
            except UnexpectedStatusError as e:
                logger.error("Cannot mark COMPLETED", version_id=svg_version_id, actual=e.actual.value)
                return

            # Auto-select this SVG version
            image.selected_svg_id = svg_version_id

        logger.info("SVG generation completed", version_id=svg_version_id, s3_key=output_key)

    async def _mark_error(self, svg_version_id: int) -> None:
        """Mark version as ERROR (internal - called on exception).

        Context must already be set by caller (process method).
        """
        locker = ProcessingLock(
            self.session,
            SvgVersion,
            SvgVersion.id == svg_version_id,  # type: ignore[arg-type]
        )
        try:
            async with locker.acquire() as lock:
                await lock.update_record(status=SvgProcessingStatus.ERROR)
        except Exception:
            pass
