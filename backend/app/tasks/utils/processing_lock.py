"""Processing lock for preventing race conditions in background tasks."""

from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum
from typing import Generic, TypeVar

import structlog
from sqlalchemy import and_
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import SQLModel, select

from app.services.exceptions import UnexpectedStatusError

logger = structlog.get_logger(__name__)

TModel = TypeVar("TModel", bound=SQLModel)
PredicateFactory = Callable[[type[TModel]], ColumnElement[bool]]


class ProcessingLockError(Exception):
    """Base lock exception."""


class RecordLockedError(ProcessingLockError):
    """Record is already locked by another worker."""


class RecordNotFoundError(ProcessingLockError):
    """Record does not exist."""


class LockNotAcquiredError(ProcessingLockError):
    """Attempted to use lock without acquiring it first."""


@dataclass
class RecordLock(Generic[TModel]):
    """Acquired lock on a database record.

    MUST be used as async context manager:
        async with locker.acquire() as lock:
            await lock.update_record(status=SomeStatus.PROCESSING)

    Using synchronous `with` or calling methods without `async with` raises LockNotAcquiredError.
    """

    session: AsyncSession
    model_class: type[TModel]
    predicate: ColumnElement[bool]
    nowait: bool = True
    status_field: str = "status"  # Column name for status field

    record: TModel | None = field(default=None, init=False)
    _tx: AsyncSessionTransaction | None = field(default=None, init=False)
    _acquired: bool = field(default=False, init=False)

    @property
    def name(self) -> str:
        return self.model_class.__name__

    def _predicate_to_text(self) -> str:
        """Format predicate for error messages."""
        bind = self.session.get_bind()
        compiled = self.predicate.compile(
            dialect=bind.dialect,
            compile_kwargs={"render_postcompile": True},
        )
        return f"{compiled} | params={compiled.params}"

    def _check_acquired(self) -> None:
        """Raise if lock not properly acquired via async with."""
        if not self._acquired or self.record is None:
            raise LockNotAcquiredError(f"{self.name}: Lock must be used with 'async with locker.acquire() as lock:'")

    async def update_record(self, **fields: object) -> None:
        """Update record fields and flush (keeps transaction open).

        Example:
            await lock.update_record(
                status=ColoringProcessingStatus.PROCESSING,
                started_at=datetime.utcnow(),
            )
        """
        self._check_acquired()
        for key, value in fields.items():
            setattr(self.record, key, value)
        await self.session.flush()

    async def mutate_record(self, fn: Callable[[TModel], None]) -> None:
        """Apply mutation function to record and flush.

        Use for complex logic with validation:
            def start_processing(m: ColoringVersion) -> None:
                if m.status not in startable_states:
                    raise ValueError("Invalid state transition")
                m.status = ColoringProcessingStatus.PROCESSING
                m.started_at = datetime.utcnow()

            await lock.mutate_record(start_processing)
        """
        self._check_acquired()
        assert self.record is not None
        fn(self.record)
        await self.session.flush()

    async def verify_and_update_status(
        self,
        expected: Enum | frozenset[Enum],
        new_status: Enum,
        **extra_fields: object,
    ) -> Enum:
        """Verify current status matches expected, then update.

        Args:
            expected: Single status or frozenset of allowed statuses
            new_status: Status to set if verification passes
            **extra_fields: Additional fields to update (e.g., started_at=datetime.now())

        Returns:
            The previous status value

        Raises:
            UnexpectedStatusError: If current status not in expected

        Example:
            async with locker.acquire() as lock:
                prev = await lock.verify_and_update_status(
                    expected=MyStatus.PROCESSING,
                    new_status=MyStatus.COMPLETED,
                    completed_at=datetime.now(UTC),
                )
        """
        self._check_acquired()
        assert self.record is not None

        expected_set = expected if isinstance(expected, frozenset) else frozenset({expected})
        current = getattr(self.record, self.status_field)

        if current not in expected_set:
            raise UnexpectedStatusError(expected=expected_set, actual=current)

        await self.update_record(**{self.status_field: new_status}, **extra_fields)
        return current  # type: ignore[no-any-return]

    def __enter__(self) -> None:
        """Prevent synchronous `with` usage."""
        raise TypeError(f"{self.__class__.__name__} must be used with 'async with', not 'with'")

    def __exit__(self, *args: object) -> None:
        pass  # Never reached

    async def __aenter__(self) -> "RecordLock[TModel]":
        # Use begin_nested() to create a savepoint within the existing transaction
        # This allows the lock to work even when a transaction is already active
        self._tx = await self.session.begin_nested()

        try:
            stmt = select(self.model_class).where(self.predicate).with_for_update(nowait=self.nowait)
            res = await self.session.execute(stmt)
            self.record = res.scalars().first()

            if self.record is None:
                raise RecordNotFoundError(f"{self.name}: {self._predicate_to_text()} not found")

            self._acquired = True
            return self

        except (OperationalError, DBAPIError) as e:
            txt = str(e).lower()
            if "lock" in txt or "could not obtain lock" in txt:
                raise RecordLockedError(f"{self.name}: {self._predicate_to_text()} locked by another worker") from e
            raise

        except BaseException:
            # Covers RecordNotFoundError, RecordLockedError, and any other exception
            # __aexit__ is NOT called if __aenter__ raises, so cleanup here
            if self._tx is not None:
                await self._tx.rollback()
                self._tx = None
            raise

    async def __aexit__(self, exc_type: type[BaseException] | None, exc: BaseException | None, tb: object) -> None:
        self._acquired = False
        if self._tx is None:
            return
        if exc_type is None:
            # Flush all pending changes (including objects modified inside lock context
            # that were loaded outside of it) before committing
            await self.session.flush()
            # Release the savepoint and commit the outer transaction
            # to make changes immediately visible to other processes
            await self._tx.commit()
            await self.session.commit()
        else:
            await self._tx.rollback()


class ProcessingLock(Generic[TModel]):
    """Reusable lock factory for background task processing.

    Supports two ways to specify the predicate:

    1. Direct predicates (preferred for simple cases):
        locker = ProcessingLock(session, ColoringVersion, ColoringVersion.id == version_id)

    2. Predicate factory (for dynamic predicates):
        locker = ProcessingLock(
            session, ColoringVersion,
            predicate_factory=lambda m: m.id == version_id
        )

    Multiple predicates are AND-ed together:
        locker = ProcessingLock(
            session, ColoringVersion,
            ColoringVersion.id == version_id,
            ColoringVersion.status == ColoringProcessingStatus.PENDING,
        )

    Usage pattern - SHORT-LIVED locks for atomic operations:
        locker = ProcessingLock(session, ColoringVersion, ColoringVersion.id == version_id)

        # First lock: check state and mark as processing
        async with locker.acquire() as lock:
            if lock.record.file_ref is not None:
                await lock.update_record(status=COMPLETED)
                return
            await lock.update_record(status=PROCESSING)

        # Do long-running work WITHOUT holding the lock
        result = await runpod.process(...)

        # Second lock: save result
        async with locker.acquire() as lock:
            await lock.update_record(file_ref=result, status=COMPLETED)
    """

    def __init__(
        self,
        session: AsyncSession,
        model_class: type[TModel],
        *predicates: ColumnElement[bool],
        predicate_factory: PredicateFactory[TModel] | None = None,
        nowait: bool = True,
        status_field: str = "status",
    ) -> None:
        self._session = session
        self._model_class = model_class
        self._nowait = nowait
        self._status_field = status_field

        # Normalize predicate
        if predicate_factory is not None:
            if predicates:
                raise TypeError("Pass either predicate_factory or predicates, not both")
            self._predicate: ColumnElement[bool] = predicate_factory(model_class)
        else:
            if not predicates:
                raise TypeError("You must pass either predicate_factory or at least one predicate")
            # AND all predicates together
            self._predicate = predicates[0] if len(predicates) == 1 else and_(*predicates)

    def acquire(self) -> RecordLock[TModel]:
        """Create a lock context manager for the record."""
        return RecordLock(
            session=self._session,
            model_class=self._model_class,
            predicate=self._predicate,
            nowait=self._nowait,
            status_field=self._status_field,
        )
