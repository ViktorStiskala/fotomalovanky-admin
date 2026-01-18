"""Processing lock utilities for preventing race conditions in background tasks."""

from enum import Enum
from typing import Any

import structlog
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

logger = structlog.get_logger(__name__)


class LockResult[T]:
    """Result of acquiring a lock on a record.

    Attributes:
        record: The locked record, or None if skipped
        skipped: Whether processing should be skipped
        reason: Why it was skipped (locked_by_another_worker, not_found,
                already_completed, already_processing)
    """

    def __init__(
        self,
        record: T | None,
        skipped: bool = False,
        reason: str | None = None,
    ):
        self.record = record
        self.skipped = skipped
        self.reason = reason

    @property
    def should_process(self) -> bool:
        """Returns True if the record was locked and should be processed."""
        return self.record is not None and not self.skipped


async def acquire_processing_lock[T](
    session: AsyncSession,
    model_class: type[T],
    record_id: int,
    *,
    completed_status: Enum,
    model_name: str | None = None,
) -> LockResult[T]:
    """Acquire an exclusive lock on a record for processing.

    This helper implements a race-condition-safe pattern for background tasks:
    1. SELECT FOR UPDATE NOWAIT - locks the row or fails immediately
    2. Check if file_ref exists (already completed but status not updated)
    3. Check if status allows processing (using status.startable_states())

    The model's status enum MUST have a `startable_states()` classmethod that
    returns a frozenset of states from which processing can start.

    Args:
        session: Database session (must be inside a transaction)
        model_class: SQLModel class to query (must have status and file_ref fields)
        record_id: Primary key of the record to lock
        completed_status: The status enum value that indicates completion
        model_name: Optional name for logging (defaults to class name)

    Returns:
        LockResult with the locked record (or None if should skip)

    Usage:
        from app.tasks.utils.processing_lock import acquire_processing_lock

        result = await acquire_processing_lock(
            session,
            ColoringVersion,
            version_id,
            completed_status=ColoringProcessingStatus.COMPLETED,
        )
        if not result.should_process:
            return  # Another worker is handling this or already complete

        version = result.record
        # ... process version ...
    """
    name = model_name or model_class.__name__

    # Try to acquire lock with NOWAIT (fail immediately if locked)
    try:
        # Use Any for dynamic attribute access on the model
        model: Any = model_class
        query = select(model_class).where(model.id == record_id).with_for_update(nowait=True)
        query_result = await session.execute(query)
        record = query_result.scalars().first()
    except (OperationalError, DBAPIError) as e:
        # Lock conflict - another worker has this record locked
        if "lock" in str(e).lower():
            logger.info(
                f"{name} locked by another worker, skipping",
                record_id=record_id,
            )
            return LockResult(None, skipped=True, reason="locked_by_another_worker")
        raise

    if not record:
        logger.error(f"{name} not found", record_id=record_id)
        return LockResult(None, skipped=True, reason="not_found")

    # Cast to Any for dynamic attribute access
    rec: Any = record

    # Check if already completed (file_ref exists but status wasn't updated)
    if rec.file_ref is not None:
        logger.warning(
            f"{name} already has file_ref, marking as completed",
            record_id=record_id,
        )
        if rec.status != completed_status:
            rec.status = completed_status
            await session.commit()
        return LockResult(None, skipped=True, reason="already_completed")

    # Check if status allows processing (use startable_states from enum)
    startable = rec.status.startable_states()
    if rec.status not in startable:
        logger.warning(
            f"{name} already being processed by another worker",
            record_id=record_id,
            status=rec.status.value,
        )
        return LockResult(None, skipped=True, reason="already_processing")

    return LockResult(record)
