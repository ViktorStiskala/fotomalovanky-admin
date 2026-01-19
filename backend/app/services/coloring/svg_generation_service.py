"""SVG vectorization processing service.

Handles Vectorizer.ai processing and S3 upload with:
- Short-lived database locks (only during state transitions)
- State verification before each transition
- Background Mercure publishes (non-blocking)
- Recovery support
"""

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coloring import ColoringVersion, SvgVersion
from app.models.enums import SvgProcessingStatus, VersionType
from app.models.order import Image, LineItem, Order
from app.services.exceptions import UnexpectedStatusError
from app.services.external.vectorizer import VectorizerApiService
from app.services.mercure.contexts import ImageStatusContext
from app.services.mercure.publish_service import MercurePublishService
from app.services.storage.paths import OrderStoragePaths
from app.services.storage.storage_service import S3StorageService
from app.tasks.utils.background_tasks import BackgroundTasks
from app.tasks.utils.processing_lock import ProcessingLock

logger = structlog.get_logger(__name__)


class SvgGenerationService:
    """Service for processing SVG vectorization via Vectorizer.ai."""

    def __init__(
        self,
        session: AsyncSession,
        storage: S3StorageService,
        vectorizer: VectorizerApiService,
        mercure_service: MercurePublishService,
        bg_tasks: BackgroundTasks | None = None,
    ):
        self.session = session
        self.storage = storage
        self.vectorizer = vectorizer
        self.mercure_service = mercure_service
        self.bg_tasks = bg_tasks

    async def process(self, svg_version_id: int, *, is_recovery: bool = False) -> None:
        """Process an SVG version."""
        locker = ProcessingLock(
            self.session,
            SvgVersion,
            SvgVersion.id == svg_version_id,  # type: ignore[arg-type]
        )

        # === LOCK 1: Check preconditions and mark as PROCESSING ===
        async with locker.acquire() as lock:
            version = lock.record
            assert version is not None

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
                current_status = SvgProcessingStatus.PROCESSING

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

        assert order.id is not None
        assert image.id is not None

        mercure = ImageStatusContext(
            service=self.mercure_service,
            bg_tasks=self.bg_tasks,
            order_id=order.id,
            image_id=image.id,
            version_id=svg_version_id,
            status_type=VersionType.SVG,
        )

        # Use the coloring_version we loaded (linked by coloring_version_id)
        if not coloring_version.file_ref:
            raise FileNotFoundError("Coloring version has no file in S3")

        mercure.publish(current_status)

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

        mercure.publish(SvgProcessingStatus.VECTORIZER_PROCESSING)

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

        mercure.publish(SvgProcessingStatus.VECTORIZER_COMPLETED)

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

        mercure.publish(SvgProcessingStatus.STORAGE_UPLOAD)

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

            image.selected_svg_id = svg_version_id

        mercure.publish(SvgProcessingStatus.COMPLETED)

        logger.info("SVG generation completed", version_id=svg_version_id, s3_key=output_key)

    async def mark_error(self, svg_version_id: int) -> None:
        """Mark version as ERROR."""
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
