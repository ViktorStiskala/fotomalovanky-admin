"""Coloring generation processing service.

Handles RunPod processing and S3 upload with:
- Short-lived database locks (only during state transitions)
- State verification before each transition (handles race conditions)
- Automatic Mercure event publishing via TrackedAsyncSession
- Recovery support (can resume from any intermediate state)
"""

from datetime import UTC, datetime

import structlog

from app.db.mercure_protocol import mercure_autotrack
from app.db.tracked_session import TrackedAsyncSession
from app.models.coloring import ColoringVersion
from app.models.enums import ColoringProcessingStatus, RunPodJobStatus
from app.models.order import Image, LineItem, Order
from app.services.exceptions import UnexpectedStatusError
from app.services.external.runpod import RunPodError, RunPodService
from app.services.mercure.events import ImageUpdateEvent
from app.services.storage.paths import OrderStoragePaths
from app.services.storage.storage_service import S3StorageService
from app.tasks.utils.processing_lock import ProcessingLock, RecordLockedError, RecordNotFoundError

logger = structlog.get_logger(__name__)


@mercure_autotrack(ImageUpdateEvent)
class ColoringGenerationService:
    """Service for processing coloring generation via RunPod.

    Uses SHORT-LIVED locks with state verification:
    - Lock only during state transitions
    - Verify current status matches expected before updating
    - If status differs, another worker modified it - abort gracefully
    - Mercure events are published automatically via TrackedAsyncSession
    """

    session: TrackedAsyncSession  # Required by MercureTrackable protocol

    def __init__(
        self,
        session: TrackedAsyncSession,
        storage: S3StorageService,
        runpod: RunPodService,
    ):
        self.session = session
        self.storage = storage
        self.runpod = runpod

    async def process(
        self,
        coloring_version_id: int,
        *,
        order_id: str,
        image_id: int,
        is_recovery: bool = False,
    ) -> None:
        """Process a coloring version.

        Args:
            coloring_version_id: ID of the ColoringVersion to process
            order_id: Order ULID for Mercure context
            image_id: Image ID for Mercure context
            is_recovery: True if called from recovery.py (affects expected states)
        """
        # MUST be first line - sets context for Mercure event publishing
        self.session.set_mercure_context(Order.id == order_id, Image.id == image_id)  # type: ignore[arg-type]

        try:
            await self._process_impl(coloring_version_id, is_recovery=is_recovery)
        except (RunPodError, FileNotFoundError, OSError) as e:
            logger.error(
                "Coloring generation failed",
                coloring_version_id=coloring_version_id,
                error=str(e),
            )
            await self._mark_error(coloring_version_id)
            raise
        except RecordNotFoundError as e:
            logger.error(str(e), coloring_version_id=coloring_version_id)
            return
        except RecordLockedError as e:
            logger.info(str(e), coloring_version_id=coloring_version_id)
            return

    async def _process_impl(self, coloring_version_id: int, *, is_recovery: bool = False) -> None:
        """Internal implementation of coloring processing."""
        locker = ProcessingLock(
            self.session,
            ColoringVersion,
            ColoringVersion.id == coloring_version_id,  # type: ignore[arg-type]
        )

        # === LOCK 1: Check preconditions and mark as PROCESSING ===
        async with locker.acquire() as lock:
            version = lock.record
            assert version is not None

            if is_recovery:
                logger.warning(
                    "Recovering coloring task",
                    version_id=version.id,
                    status=version.status.value,
                    has_runpod_job_id=version.runpod_job_id is not None,
                    runpod_job_id=version.runpod_job_id,
                    has_file_ref=version.file_ref is not None,
                )

            if version.file_ref is not None:
                logger.warning(
                    "ColoringVersion already has file_ref, marking completed",
                    version_id=version.id,
                )
                await lock.update_record(status=ColoringProcessingStatus.COMPLETED)
                return

            # Recovery can start from intermediate states, normal only from startable/retryable
            if is_recovery:
                allowed = version.status.meta.is_recoverable or version.status.meta.is_startable
            else:
                allowed = version.status.meta.is_startable or version.status.meta.is_retryable

            if not allowed:
                logger.warning(
                    "ColoringVersion not in processable state",
                    version_id=version.id,
                    status=version.status.value,
                    is_recovery=is_recovery,
                )
                return

            # Capture values needed outside lock
            image_id = version.image_id
            existing_job_id = version.runpod_job_id
            megapixels = version.megapixels
            steps = version.steps
            current_status = version.status

            # Only update to PROCESSING if not already past it
            if current_status in {ColoringProcessingStatus.PENDING, ColoringProcessingStatus.QUEUED}:
                await lock.update_record(
                    status=ColoringProcessingStatus.PROCESSING,
                    started_at=datetime.now(UTC),
                )

        # === OUTSIDE LOCK: Load related objects ===
        image = await self.session.get(Image, image_id)
        if not image:
            raise ValueError(f"Image {image_id} not found")

        line_item = await self.session.get(LineItem, image.line_item_id)
        if not line_item:
            raise ValueError(f"LineItem {image.line_item_id} not found")

        order = await self.session.get(Order, line_item.order_id)
        if not order:
            raise ValueError(f"Order {line_item.order_id} not found")

        if not image.file_ref:
            raise FileNotFoundError("Image not uploaded to S3 yet")

        # === LOCK 2: Submit to RunPod (if no existing job) ===
        if existing_job_id:
            job_id = existing_job_id
            logger.info("Resuming existing RunPod job", version_id=coloring_version_id, job_id=job_id)
        else:
            # Download image OUTSIDE lock
            image_data = await self.storage.download(image.file_ref)

            # Lock and verify no other worker started submission
            async with locker.acquire() as lock:
                version = lock.record
                assert version is not None

                if version.runpod_job_id is not None:
                    logger.info(
                        "Another worker already submitted RunPod job",
                        version_id=coloring_version_id,
                        job_id=version.runpod_job_id,
                    )
                    return

                await lock.update_record(status=ColoringProcessingStatus.RUNPOD_SUBMITTING)

            # Submit to RunPod OUTSIDE lock
            job_id = await self.runpod.submit_job(
                image_data=image_data,
                megapixels=megapixels,
                steps=steps,
            )

            # Save job_id with lock (atomic)
            async with locker.acquire() as lock:
                await lock.update_record(
                    runpod_job_id=job_id,
                    status=ColoringProcessingStatus.RUNPOD_SUBMITTED,
                )

        # === OUTSIDE LOCK: Poll RunPod (long-running) ===
        async def on_runpod_status(runpod_status: str) -> None:
            # Map RunPod status to our status
            if runpod_status == RunPodJobStatus.IN_QUEUE:
                new_status = ColoringProcessingStatus.RUNPOD_QUEUED
            elif runpod_status == RunPodJobStatus.IN_PROGRESS:
                new_status = ColoringProcessingStatus.RUNPOD_PROCESSING
            else:
                return

            logger.info(
                "Updating status from RunPod callback",
                version_id=coloring_version_id,
                runpod_status=runpod_status,
                new_status=new_status.value,
            )

            async with locker.acquire() as lock:
                version = lock.record
                assert version is not None

                if version.status not in ColoringProcessingStatus.awaiting_external_states():
                    logger.warning(
                        "Status changed unexpectedly during polling",
                        version_id=coloring_version_id,
                        actual=version.status.value,
                    )
                    return

                logger.info(
                    "Updating coloring version status",
                    version_id=coloring_version_id,
                    old_status=version.status.value,
                    new_status=new_status.value,
                )
                await lock.update_record(status=new_status)

        result_data = await self.runpod.poll_job(job_id, on_status_change=on_runpod_status)

        # === LOCK 3: Mark RUNPOD_COMPLETED ===
        async with locker.acquire() as lock:
            try:
                await lock.verify_and_update_status(
                    expected=ColoringProcessingStatus.awaiting_external_states(),
                    new_status=ColoringProcessingStatus.RUNPOD_COMPLETED,
                )
            except UnexpectedStatusError as e:
                logger.error(
                    "Cannot mark RUNPOD_COMPLETED - unexpected status",
                    version_id=coloring_version_id,
                    actual=e.actual.value,
                )
                return

        # === LOCK 4: Verify RUNPOD_COMPLETED and mark STORAGE_UPLOAD ===
        async with locker.acquire() as lock:
            try:
                await lock.verify_and_update_status(
                    expected=ColoringProcessingStatus.RUNPOD_COMPLETED,
                    new_status=ColoringProcessingStatus.STORAGE_UPLOAD,
                )
            except UnexpectedStatusError as e:
                logger.error(
                    "Cannot start upload - unexpected status",
                    version_id=coloring_version_id,
                    actual=e.actual.value,
                )
                return

        # === OUTSIDE LOCK: Upload to S3 ===
        # Reload version to get the version object for path generation
        version_for_path = await self.session.get(ColoringVersion, coloring_version_id)
        assert version_for_path is not None

        paths = OrderStoragePaths(order)
        output_key = paths.coloring_version(line_item, image, version_for_path)

        file_ref = await self.storage.upload(
            upload_to=output_key,
            data=result_data,
            content_type="image/png",
        )

        # === LOCK 5: Verify STORAGE_UPLOAD and mark COMPLETED ===
        async with locker.acquire() as lock:
            try:
                await lock.verify_and_update_status(
                    expected=ColoringProcessingStatus.STORAGE_UPLOAD,
                    new_status=ColoringProcessingStatus.COMPLETED,
                    file_ref=file_ref,
                    runpod_job_id=None,
                    completed_at=datetime.now(UTC),
                )
            except UnexpectedStatusError as e:
                logger.error(
                    "Cannot mark COMPLETED - unexpected status",
                    version_id=coloring_version_id,
                    actual=e.actual.value,
                )
                return

            # Auto-select this coloring version
            image.selected_coloring_id = coloring_version_id

        logger.info("Coloring generation completed", version_id=coloring_version_id, s3_key=output_key)

    async def _mark_error(self, coloring_version_id: int) -> None:
        """Mark version as ERROR (internal - called on exception).

        Context must already be set by caller (process method).
        """
        locker = ProcessingLock(
            self.session,
            ColoringVersion,
            ColoringVersion.id == coloring_version_id,  # type: ignore[arg-type]
        )
        try:
            async with locker.acquire() as lock:
                await lock.update_record(status=ColoringProcessingStatus.ERROR)
        except Exception:
            pass  # Best effort
