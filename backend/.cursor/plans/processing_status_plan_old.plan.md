# Redesign Processing Status with Flags

## Clean Syntax Design

Direct flags with runtime validation via `__or__` override:

```python
class ColoringProcessingStatus(ProcessingStatusEnum):
    """Status for coloring generation (RunPod).
    
    Status flow:
        PENDING -> QUEUED -> PROCESSING -> RUNPOD_SUBMITTING -> RUNPOD_SUBMITTED
        -> RUNPOD_QUEUED -> RUNPOD_PROCESSING -> RUNPOD_COMPLETED
        -> STORAGE_UPLOAD -> COMPLETED
    """
    
    PENDING = Status("pending", Flags.STARTABLE, display="Čeká na odeslání")
    QUEUED = Status("queued", Flags.STARTABLE | Flags.RECOVERABLE, display="Čeká ve frontě")
    PROCESSING = Status("processing", Flags.RECOVERABLE, display="Zpracovává se")
    RUNPOD_SUBMITTING = Status("runpod_submitting", Flags.RECOVERABLE, display="Runpod: odesílání")
    RUNPOD_SUBMITTED = Status("runpod_submitted", Flags.RECOVERABLE | Flags.AWAITING_EXTERNAL, display="Runpod: přijato")
    RUNPOD_QUEUED = Status("runpod_queued", Flags.RECOVERABLE | Flags.AWAITING_EXTERNAL, display="Runpod: ve frontě")
    RUNPOD_PROCESSING = Status("runpod_processing", Flags.RECOVERABLE | Flags.AWAITING_EXTERNAL, display="Runpod: zpracování")
    RUNPOD_COMPLETED = Status("runpod_completed", Flags.RECOVERABLE, display="Runpod: dokončeno")
    STORAGE_UPLOAD = Status("storage_upload", Flags.RECOVERABLE, display="Nahrávání na S3")
    COMPLETED = Status("completed", Flags.FINAL, display="Dokončeno")
    ERROR = Status("error", Flags.FINAL | Flags.RETRYABLE, display="Chyba")
    RUNPOD_CANCELLED = Status("runpod_cancelled", Flags.FINAL | Flags.RETRYABLE, display="Zrušeno")
```

## Valid Combinations

| Flags | Meaning | Used for |

|-------|---------|----------|

| `STARTABLE` | Initial state | PENDING |

| `STARTABLE \| RECOVERABLE` | In queue, can restart or recover | QUEUED |

| `RECOVERABLE` | Active processing, recover if interrupted | PROCESSING, RUNPOD_SUBMITTING, RUNPOD_COMPLETED, STORAGE_UPLOAD |

| `RECOVERABLE \| AWAITING_EXTERNAL` | Waiting for external service (poll/webhook) | RUNPOD_SUBMITTED, RUNPOD_QUEUED, RUNPOD_PROCESSING |

| `FINAL` | Successfully completed, not retryable | COMPLETED |

| `FINAL \| RETRYABLE` | Failed, user can retry | ERROR, RUNPOD_CANCELLED |

This allows for new services that might have `FINAL` without `RETRYABLE` (permanent failures).

## Current Rules

| Rule | Effect |

|------|--------|

| `FlagRule(when=RETRYABLE, required=FINAL)` | RETRYABLE requires FINAL |

| `FlagRule(when=FINAL, forbidden=RECOVERABLE\|STARTABLE\|AWAITING_EXTERNAL)` | FINAL forbids RECOVERABLE, STARTABLE, AWAITING_EXTERNAL |

| `FlagRule(when=AWAITING_EXTERNAL, required=RECOVERABLE, forbidden=STARTABLE)` | AWAITING_EXTERNAL requires RECOVERABLE, forbids STARTABLE |

## Implementation

### 1. New file: [`backend/app/models/status.py`](backend/app/models/status.py)

```python
from dataclasses import dataclass
from enum import IntFlag, StrEnum, auto
from typing import ClassVar


class Flags(IntFlag):
    """Processing status metadata flags.
    
    Flags:
        STARTABLE         - Task can be picked up by a worker (initial states)
        RECOVERABLE       - Task recovery should re-dispatch if stuck (active states)
        AWAITING_EXTERNAL - External service is processing async (requires polling/webhook)
        FINAL             - Final state, no more processing
        RETRYABLE         - User can manually retry (requires FINAL)
    """
    NONE = 0
    STARTABLE = auto()         # Task can be picked up by a worker
    RECOVERABLE = auto()       # Task recovery should re-dispatch if stuck
    AWAITING_EXTERNAL = auto() # External service processing async (poll or wait for webhook)
    FINAL = auto()             # Final state, no more processing
    RETRYABLE = auto()         # User can retry (only valid with FINAL)
    
    # Validation rules - populated after class definition
    RULES: ClassVar[set[FlagRule]] = set()
    
    def __or__(self, other: "Flags") -> "Flags":
        result = Flags(super().__or__(other))
        self._validate_flags(result)
        return result

    def __ror__(self, other: "Flags") -> "Flags":
        return self.__or__(other)
    
    @classmethod
    def _validate_flags(cls, value: "Flags") -> None:
        """Validate flag combination against rules."""
        for rule in cls.RULES:
            # Rule triggers only if all `when` bits are present
            if (value & rule.when) != rule.when:
                continue

            missing = rule.required & ~value
            present_forbidden = value & rule.forbidden

            if missing or present_forbidden:
                parts: list[str] = []
                if missing:
                    parts.append(f"{missing.name.replace('|', ' and ')} must be present")
                if present_forbidden:
                    parts.append(f"{present_forbidden.name.replace('|', ' and ')} cannot be present")

                when_txt = rule.when.name.replace("|", " and ")
                raise ValueError(f"When {when_txt}: " + " and ".join(parts))


@dataclass(frozen=True)
class FlagRule:
    """Rule for validating flag combinations.
    
    Attributes:
        when: All these bits must be present to trigger the rule
        required: These bits must also be present (when rule triggers)
        forbidden: These bits must be absent (when rule triggers)
    """
    when: Flags
    required: Flags = Flags.NONE
    forbidden: Flags = Flags.NONE

    def __post_init__(self) -> None:
        if self.when == Flags.NONE:
            raise ValueError("when may not be empty")
        if self.required & self.forbidden:
            raise ValueError("required and forbidden overlap")


# Define validation rules after class definition
Flags.RULES = {
    # RETRYABLE requires FINAL
    FlagRule(
        when=Flags.RETRYABLE,
        required=Flags.FINAL,
    ),
    # FINAL forbids RECOVERABLE, STARTABLE, and AWAITING_EXTERNAL
    FlagRule(
        when=Flags.FINAL,
        forbidden=Flags.RECOVERABLE | Flags.STARTABLE | Flags.AWAITING_EXTERNAL,
    ),
    # AWAITING_EXTERNAL requires RECOVERABLE (must be able to resume polling)
    # and forbids STARTABLE (already past the start phase)
    FlagRule(
        when=Flags.AWAITING_EXTERNAL,
        required=Flags.RECOVERABLE,
        forbidden=Flags.STARTABLE,
    ),
}

@dataclass(frozen=True, slots=True)
class Status:
    """Status definition with value, flags, and display name."""
    value: str
    flags: Flags = Flags.NONE
    display: str = ""
    
    @property
    def is_startable(self) -> bool:
        return bool(self.flags & Flags.STARTABLE)
    
    @property
    def is_recoverable(self) -> bool:
        return bool(self.flags & Flags.RECOVERABLE)
    
    @property
    def is_final(self) -> bool:
        return bool(self.flags & Flags.FINAL)
    
    @property
    def is_retryable(self) -> bool:
        return bool(self.flags & Flags.RETRYABLE)
    
    @property
    def is_awaiting_external(self) -> bool:
        return bool(self.flags & Flags.AWAITING_EXTERNAL)

class ProcessingStatusEnum(StrEnum):
    """Base class for processing status enums with metadata support.
    
    Subclasses define members using Status objects:
        PENDING = Status("pending", Flags.STARTABLE, display="...")
    
    The enum value is the string (for DB), metadata accessible via .meta
    """
    _status_registry: ClassVar[dict[str, Status]] = {}
    
    def _generate_next_value_(name, start, count, last_values):
        # This is called during enum creation
        # The actual value extraction happens in __new__
        return name.lower()
    
    def __new__(cls, status: Status | str):
        # Handle both Status objects and plain strings
        if isinstance(status, Status):
            value = status.value
            # Store metadata in class registry
            if not hasattr(cls, '_status_registry') or cls._status_registry is cls.__bases__[0]._status_registry:
                cls._status_registry = {}
            cls._status_registry[value] = status
        else:
            value = status
        
        obj = str.__new__(cls, value)
        obj._value_ = value
        return obj
    
    @property
    def meta(self) -> Status:
        """Get metadata for this status."""
        return self._status_registry.get(self._value_, Status(self._value_))
    
    @classmethod
    def intermediate_states(cls) -> frozenset["ProcessingStatusEnum"]:
        """States where task recovery should re-dispatch (RECOVERABLE flag)."""
        return frozenset(s for s in cls if s.meta.is_recoverable)
    
    @classmethod
    def startable_states(cls) -> frozenset["ProcessingStatusEnum"]:
        """States from which a task can be started (STARTABLE or RETRYABLE).
        
        Includes initial states (PENDING, QUEUED) and failed states (ERROR, CANCELLED)
        that can be retried by user action.
        """
        return frozenset(s for s in cls if s.meta.is_startable or s.meta.is_retryable)
    
    @classmethod
    def final_states(cls) -> frozenset["ProcessingStatusEnum"]:
        """Final states (FINAL flag) - completed, error, cancelled."""
        return frozenset(s for s in cls if s.meta.is_final)
    
    @classmethod
    def retryable_states(cls) -> frozenset["ProcessingStatusEnum"]:
        """States where user can manually retry (RETRYABLE flag)."""
        return frozenset(s for s in cls if s.meta.is_retryable)
    
    @classmethod
    def awaiting_external_states(cls) -> frozenset["ProcessingStatusEnum"]:
        """States where external service is processing async (poll or webhook)."""
        return frozenset(s for s in cls if s.meta.is_awaiting_external)
```

### 2. Refactor [`backend/app/models/enums.py`](backend/app/models/enums.py)

Move PgEnum definitions here (from `coloring.py`) alongside the enums:

```python
"""Enum definitions for database models."""

from enum import StrEnum

from sqlalchemy.dialects.postgresql import ENUM as PgEnum

from app.models.status import Flags, ProcessingStatusEnum, Status


class OrderStatus(StrEnum):
    """Status of an order in the processing pipeline."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    READY_FOR_REVIEW = "ready_for_review"
    ERROR = "error"


class ColoringProcessingStatus(ProcessingStatusEnum):
    """Status for coloring generation (RunPod).
    
    Status flow (roughly ordered):
        PENDING -> PROCESSING -> RUNPOD_SUBMITTING -> RUNPOD_SUBMITTED
        -> RUNPOD_QUEUED -> RUNPOD_PROCESSING -> RUNPOD_COMPLETED
        -> STORAGE_UPLOAD -> COMPLETED
    
    Error/cancelled states can occur from any RUNPOD_* or STORAGE_UPLOAD state.
    """
    
    PENDING = Status("pending", Flags.STARTABLE, display="Čeká na odeslání")
    QUEUED = Status("queued", Flags.STARTABLE | Flags.RECOVERABLE, display="Čeká ve frontě")
    PROCESSING = Status("processing", Flags.RECOVERABLE, display="Zpracovává se")
    RUNPOD_SUBMITTING = Status("runpod_submitting", Flags.RECOVERABLE, display="Runpod: odesílání")
    RUNPOD_SUBMITTED = Status("runpod_submitted", Flags.RECOVERABLE | Flags.AWAITING_EXTERNAL, display="Runpod: přijato")
    RUNPOD_QUEUED = Status("runpod_queued", Flags.RECOVERABLE | Flags.AWAITING_EXTERNAL, display="Runpod: ve frontě")
    RUNPOD_PROCESSING = Status("runpod_processing", Flags.RECOVERABLE | Flags.AWAITING_EXTERNAL, display="Runpod: zpracování")
    RUNPOD_COMPLETED = Status("runpod_completed", Flags.RECOVERABLE, display="Runpod: dokončeno")
    STORAGE_UPLOAD = Status("storage_upload", Flags.RECOVERABLE, display="Nahrávání na S3")
    COMPLETED = Status("completed", Flags.FINAL, display="Dokončeno")
    ERROR = Status("error", Flags.FINAL | Flags.RETRYABLE, display="Chyba")
    RUNPOD_CANCELLED = Status("runpod_cancelled", Flags.FINAL | Flags.RETRYABLE, display="Zrušeno")


class SvgProcessingStatus(ProcessingStatusEnum):
    """Status for SVG vectorization (Vectorizer.ai).
    
    Status flow (roughly ordered):
        PENDING -> PROCESSING -> VECTORIZER_PROCESSING -> VECTORIZER_COMPLETED
        -> STORAGE_UPLOAD -> COMPLETED
    """
    
    PENDING = Status("pending", Flags.STARTABLE, display="Čeká na odeslání")
    QUEUED = Status("queued", Flags.STARTABLE | Flags.RECOVERABLE, display="Čeká ve frontě")
    PROCESSING = Status("processing", Flags.RECOVERABLE, display="Zpracovává se")
    VECTORIZER_PROCESSING = Status("vectorizer_processing", Flags.RECOVERABLE | Flags.AWAITING_EXTERNAL, display="Vectorizer: zpracování")
    VECTORIZER_COMPLETED = Status("vectorizer_completed", Flags.RECOVERABLE, display="Vectorizer: dokončeno")
    STORAGE_UPLOAD = Status("storage_upload", Flags.RECOVERABLE, display="Nahrávání na S3")
    COMPLETED = Status("completed", Flags.FINAL, display="Dokončeno")
    ERROR = Status("error", Flags.FINAL | Flags.RETRYABLE, display="Chyba")


class VersionType(StrEnum):
    """Type of generated version - used in storage paths and API routes."""

    COLORING = "coloring"
    SVG = "svg"


class RunPodJobStatus(StrEnum):
    """Status values returned by RunPod API."""
    
    COMPLETED = "COMPLETED"
    IN_QUEUE = "IN_QUEUE"
    IN_PROGRESS = "IN_PROGRESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


# PostgreSQL enum types - define alongside the enums for co-location
COLORING_STATUS_PG_ENUM = PgEnum(
    ColoringProcessingStatus,
    name="coloringprocessingstatus",
    create_type=False,
    values_callable=lambda e: [member.value for member in e],
)

SVG_STATUS_PG_ENUM = PgEnum(
    SvgProcessingStatus,
    name="svgprocessingstatus",
    create_type=False,
    values_callable=lambda e: [member.value for member in e],
)
```

### 2b. Update [`backend/app/models/coloring.py`](backend/app/models/coloring.py)

Import PgEnum types from enums.py instead of defining them locally:

```python
# Remove these local definitions:
# _coloring_status_enum = PgEnum(...)
# _svg_status_enum = PgEnum(...)

# Import from enums.py:
from app.models.enums import (
    ColoringProcessingStatus,
    SvgProcessingStatus,
    COLORING_STATUS_PG_ENUM,
    SVG_STATUS_PG_ENUM,
)

# Use in model fields:
class ColoringVersion(SQLModel, table=True):
    status: ColoringProcessingStatus = Field(
        default=ColoringProcessingStatus.PENDING,
        sa_column=Column(COLORING_STATUS_PG_ENUM, nullable=False),
    )
```

### 3. Update [`backend/app/services/storage/storage_service.py`](backend/app/services/storage/storage_service.py)

Add tenacity retries to `upload`:

```python
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type
from botocore.exceptions import ClientError

@retry(
    retry=retry_if_exception_type((ClientError, OSError)),
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    reraise=True,
)
async def upload(self, ...) -> S3ObjectRefData:
    ...
```

### 4. Update tasks to use STORAGE_UPLOAD status

In [`backend/app/tasks/coloring/generate_coloring.py`](backend/app/tasks/coloring/generate_coloring.py):

```python
# After RunPod completes:
await update_status(ColoringProcessingStatus.STORAGE_UPLOAD)

# Upload result to S3
file_ref = await storage.upload(...)
```

Same for [`backend/app/tasks/coloring/vectorize_image.py`](backend/app/tasks/coloring/vectorize_image.py).

### 4b. Refactor [`backend/app/tasks/utils/processing_lock.py`](backend/app/tasks/utils/processing_lock.py)

Rewrite to class-based context manager with short-lived locks pattern.

```python
"""Processing lock for preventing race conditions in background tasks."""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Generic, TypeVar

import structlog
from sqlalchemy import and_
from sqlalchemy.exc import DBAPIError, OperationalError
from sqlalchemy.ext.asyncio import AsyncSession, AsyncSessionTransaction
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.sql.elements import ColumnElement
from sqlmodel import select

logger = structlog.get_logger(__name__)

TModel = TypeVar("TModel", bound=DeclarativeBase)
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
            raise LockNotAcquiredError(
                f"{self.name}: Lock must be used with 'async with locker.acquire() as lock:'"
            )

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
        fn(self.record)
        await self.session.flush()

    def __enter__(self) -> None:
        """Prevent synchronous `with` usage."""
        raise TypeError(
            f"{self.__class__.__name__} must be used with 'async with', not 'with'"
        )

    def __exit__(self, *args: object) -> None:
        pass  # Never reached

    async def __aenter__(self) -> "RecordLock[TModel]":
        self._tx = await self.session.begin()
        
        try:
            stmt = (
                select(self.model_class)
                .where(self.predicate)
                .with_for_update(nowait=self.nowait)
            )
            res = await self.session.execute(stmt)
            self.record = res.scalars().first()

            if self.record is None:
                raise RecordNotFoundError(
                    f"{self.name}: {self._predicate_to_text()} not found"
                )
            
            self._acquired = True
            return self

        except (OperationalError, DBAPIError) as e:
            txt = str(e).lower()
            if "lock" in txt or "could not obtain lock" in txt:
                raise RecordLockedError(
                    f"{self.name}: {self._predicate_to_text()} locked by another worker"
                ) from e
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
            await self._tx.commit()
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
    ) -> None:
        self._session = session
        self._model_class = model_class
        self._nowait = nowait

        # Normalize predicate
        if predicate_factory is not None:
            if predicates:
                raise TypeError(
                    "Pass either predicate_factory or predicates, not both"
                )
            self._predicate: ColumnElement[bool] = predicate_factory(model_class)
        else:
            if not predicates:
                raise TypeError(
                    "You must pass either predicate_factory or at least one predicate"
                )
            # AND all predicates together
            self._predicate = (
                predicates[0]
                if len(predicates) == 1
                else and_(*predicates)
            )

    def acquire(self) -> RecordLock[TModel]:
        """Create a lock context manager for the record."""
        return RecordLock(
            session=self._session,
            model_class=self._model_class,
            predicate=self._predicate,
            nowait=self._nowait,
        )
```

### 4c. Create [`backend/app/models/base_version.py`](backend/app/models/base_version.py)

Extract shared fields from ColoringVersion and SvgVersion:

```python
"""Base model for processing versions (coloring, SVG)."""

from datetime import datetime

from sqlmodel import Field, SQLModel

from app.models.types import S3ObjectRef, S3ObjectRefData


class BaseVersion(SQLModel):
    """Abstract base for ColoringVersion and SvgVersion.
    
    Shared fields:
    - id, image_id, version number
    - file_ref (S3 storage)
    - timestamps
    """
    id: int | None = Field(default=None, primary_key=True)
    image_id: int = Field(foreign_key="images.id", index=True)
    version: int = Field(default=1)
    
    file_ref: S3ObjectRefData | None = Field(
        default=None,
        sa_type=S3ObjectRef,
    )
    
    created_at: datetime = Field(default_factory=datetime.utcnow)
    started_at: datetime | None = Field(default=None)
    completed_at: datetime | None = Field(default=None)
```

Update `ColoringVersion` and `SvgVersion` in [`backend/app/models/coloring.py`](backend/app/models/coloring.py):

```python
from app.models.base_version import BaseVersion
from app.models.enums import (
    ColoringProcessingStatus,
    SvgProcessingStatus,
    COLORING_STATUS_PG_ENUM,
    SVG_STATUS_PG_ENUM,
)


class ColoringVersion(BaseVersion, table=True):
    """Coloring version with RunPod-specific fields."""
    __tablename__ = "coloring_versions"
    
    status: ColoringProcessingStatus = Field(
        default=ColoringProcessingStatus.PENDING,
        sa_column=Column(COLORING_STATUS_PG_ENUM, nullable=False),
    )
    
    # RunPod-specific
    runpod_job_id: str | None = Field(default=None, max_length=100)
    megapixels: float = Field(default=1.0)
    steps: int = Field(default=4)


class SvgVersion(BaseVersion, table=True):
    """SVG version with Vectorizer.ai-specific fields."""
    __tablename__ = "svg_versions"
    
    status: SvgProcessingStatus = Field(
        default=SvgProcessingStatus.PENDING,
        sa_column=Column(SVG_STATUS_PG_ENUM, nullable=False),
    )
    
    # Vectorizer-specific (if any)
    vectorizer_job_id: str | None = Field(default=None, max_length=100)
```

### 4d. Refactor Mercure service and create contexts

#### Create `backend/app/services/mercure/` folder

```bash
# Create directory and empty __init__.py (per project rules)
mkdir -p backend/app/services/mercure
touch backend/app/services/mercure/__init__.py
```

Add to `__init__.py`:

```python
"""Mercure publishing services."""
```

#### Move [`backend/app/services/external/mercure.py`](backend/app/services/external/mercure.py) → [`backend/app/services/mercure/publish_service.py`](backend/app/services/mercure/publish_service.py)

```python
"""Mercure publishing service."""

import httpx
import structlog

from app.config import settings
from app.models.events import (
    ImageStatusEvent,
    ImageUpdateEvent,
    ListUpdateEvent,
    MercureEvent,
    OrderUpdateEvent,
)

logger = structlog.get_logger(__name__)


class MercurePublishService:
    """Service for publishing events to Mercure hub."""
    
    async def _publish(self, topics: list[str], event: MercureEvent) -> None:
        """Publish an event to Mercure topics."""
        if not settings.mercure_publisher_jwt:
            logger.warning("Mercure publisher JWT not configured, skipping publish")
            return
        
        async with httpx.AsyncClient() as client:
            try:
                # Mercure expects form data
                data = {
                    "topic": topics,
                    "data": event.model_dump_json(),
                }
                response = await client.post(
                    settings.mercure_hub_url,
                    data=data,
                    headers={"Authorization": f"Bearer {settings.mercure_publisher_jwt}"},
                    timeout=5.0,
                )
                response.raise_for_status()
                logger.debug("Published Mercure event", topics=topics, type=event.type)
            except Exception as e:
                logger.error("Failed to publish Mercure event", error=str(e), topics=topics)

    async def publish_order_update(self, order_id: str) -> None:
        """Publish order update event."""
        event = OrderUpdateEvent(type="order_update", order_id=order_id)
        await self._publish(
            topics=["orders", f"orders/{order_id}"],
            event=event,
        )

    async def publish_list_update(self) -> None:
        """Publish order list update event."""
        event = ListUpdateEvent(type="list_update")
        await self._publish(topics=["orders"], event=event)

    async def publish_image_update(self, order_id: str, image_id: int) -> None:
        """Publish image update event."""
        event = ImageUpdateEvent(type="image_update", order_id=order_id, image_id=image_id)
        await self._publish(
            topics=["orders", f"orders/{order_id}"],
            event=event,
        )

    async def publish_image_status(
        self,
        order_id: str,
        image_id: int,
        status_type: str,
        version_id: int,
        status: str,
    ) -> None:
        """Publish image processing status event."""
        event = ImageStatusEvent(
            type="image_status",
            order_id=order_id,
            image_id=image_id,
            status_type=status_type,
            version_id=version_id,
            status=status,
        )
        await self._publish(
            topics=["orders", f"orders/{order_id}"],
            event=event,
        )
```

#### Create [`backend/app/services/mercure/contexts.py`](backend/app/services/mercure/contexts.py)

Base class with optional `bg_tasks` and subclasses that define publish behavior:

```python
"""Mercure publishing contexts - capture common arguments for repeated publishes."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.models.enums import VersionType  # Reuse existing enum, don't duplicate

if TYPE_CHECKING:
    from app.services.mercure.publish_service import MercurePublishService
    from app.tasks.utils.background_tasks import BackgroundTasks


@dataclass
class MercureContext(ABC):
    """Base class for Mercure publishing contexts.
    
    Captures common arguments (service, order_id, etc.) so you only need
    to pass the changing value (e.g., status) on each publish.
    
    Supports two modes:
    - With bg_tasks: `mercure.publish(status)` schedules non-blocking
    - Without bg_tasks: `await mercure.publish_async(status)` awaits directly
    
    Subclasses implement `_build_coro()` to create the actual publish coroutine.
    """
    
    service: "MercurePublishService"
    bg_tasks: "BackgroundTasks | None" = field(default=None)
    
    @abstractmethod
    def _build_coro(self, *args: Any, **kwargs: Any) -> Awaitable[None]:
        """Build the coroutine to publish. Subclasses define the actual call."""
        ...
    
    def publish(self, *args: Any, **kwargs: Any) -> None:
        """Schedule publish as background task (non-blocking).
        
        Requires bg_tasks to be set in constructor.
        """
        if self.bg_tasks is None:
            raise RuntimeError(
                "Cannot use publish() without bg_tasks. "
                "Use publish_async() or pass bg_tasks to constructor."
            )
        self.bg_tasks.run(self._build_coro(*args, **kwargs))
    
    async def publish_async(self, *args: Any, **kwargs: Any) -> None:
        """Directly await the publish (blocking)."""
        await self._build_coro(*args, **kwargs)


@dataclass
class ImageStatusContext(MercureContext):
    """Context for publishing image status updates during processing.
    
    Usage (background):
        mercure = ImageStatusContext(
            service=mercure_service,
            bg_tasks=bg_tasks,
            order_id=order.id,
            image_id=image.id,
            version_id=version.id,
            status_type=VersionType.COLORING,
        )
        mercure.publish(ColoringProcessingStatus.PROCESSING)  # Non-blocking
    
    Usage (direct):
        mercure = ImageStatusContext(
            service=mercure_service,
            order_id=order.id,
            ...
        )
        await mercure.publish_async(ColoringProcessingStatus.PROCESSING)  # Blocking
    """
    
    order_id: str = ""
    image_id: int = 0
    version_id: int = 0
    status_type: VersionType = VersionType.COLORING
    
    def _build_coro(self, status: Any) -> Awaitable[None]:
        """Build coroutine for image status publish."""
        return self.service.publish_image_status(
            order_id=self.order_id,
            image_id=self.image_id,
            status_type=self.status_type.value,
            version_id=self.version_id,
            status=status.value if hasattr(status, "value") else str(status),
        )


@dataclass
class OrderUpdateContext(MercureContext):
    """Context for publishing order updates.
    
    Usage:
        mercure = OrderUpdateContext(service=mercure_service, bg_tasks=bg_tasks, order_id=order.id)
        mercure.publish()  # No arguments needed
    """
    
    order_id: str = ""
    
    def _build_coro(self) -> Awaitable[None]:
        """Build coroutine for order update publish."""
        return self.service.publish_order_update(self.order_id)


@dataclass
class ListUpdateContext(MercureContext):
    """Context for publishing order list updates.
    
    Usage:
        mercure = ListUpdateContext(service=mercure_service, bg_tasks=bg_tasks)
        mercure.publish()
    """
    
    def _build_coro(self) -> Awaitable[None]:
        """Build coroutine for list update publish."""
        return self.service.publish_list_update()


@dataclass  
class ImageUpdateContext(MercureContext):
    """Context for publishing image metadata updates (e.g., selection changes).
    
    Usage:
        mercure = ImageUpdateContext(service=mercure_service, bg_tasks=bg_tasks, order_id=order.id, image_id=image.id)
        mercure.publish()
    """
    
    order_id: str = ""
    image_id: int = 0
    
    def _build_coro(self) -> Awaitable[None]:
        """Build coroutine for image update publish."""
        return self.service.publish_image_update(
            order_id=self.order_id,
            image_id=self.image_id,
        )
```

#### Create [`backend/app/services/mercure/__init__.py`](backend/app/services/mercure/__init__.py)

Empty docstring only (per project rules).

### 4e. Create shared exception [`backend/app/services/coloring/exceptions.py`](backend/app/services/coloring/exceptions.py)

Add `UnexpectedStatusError`:

```python
# Add to existing exceptions file:

class UnexpectedStatusError(Exception):
    """Status in DB doesn't match expected status - another worker modified it."""
    
    def __init__(self, expected: Enum, actual: Enum):
        self.expected = expected
        self.actual = actual
        super().__init__(f"Expected status {expected.value}, got {actual.value}")
```

### 4f. Create [`backend/app/tasks/utils/background_tasks.py`](backend/app/tasks/utils/background_tasks.py)

Background task manager for fire-and-forget operations (e.g., Mercure publishes):

```python
"""Background task utilities for async fire-and-forget operations."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")
P = ParamSpec("P")


class BackgroundTasks:
    """Collects background asyncio tasks that should finish before the function returns.
    
    Usage:
        bg = BackgroundTasks()
        bg.run(some_coroutine())
        bg.run(another_coroutine())
        await bg.wait(timeout=30)  # Wait for all tasks with timeout
    
    Typically used via the @background_tasks decorator which handles wait() automatically.
    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task[Any]] = []
        self._counters: dict[str, int] = defaultdict(int)

    def _task_key(self, coro: Awaitable[Any]) -> str:
        """Generate a human-readable key for the task."""
        # Prefer __qualname__ for methods
        name = getattr(coro, "__qualname__", None)
        if name:
            return name

        # Fall back to code object name for coroutines
        code = getattr(coro, "cr_code", None)
        if code:
            return code.co_name

        return "task"

    def run(self, coro: Awaitable[Any]) -> None:
        """Schedule a coroutine as a background task.
        
        The task will be awaited when wait() is called.
        """
        key = self._task_key(coro)
        self._counters[key] += 1
        name = f"bg:{key}:{self._counters[key]}"

        task = asyncio.create_task(coro, name=name)
        self._tasks.append(task)

    async def wait(self, *, timeout: float) -> None:
        """Wait for all background tasks to complete with timeout.
        
        If timeout is exceeded, remaining tasks are cancelled.
        Exceptions from tasks are logged but not raised.
        """
        if not self._tasks:
            return

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=timeout,
            )
            # Log any exceptions
            for task, result in zip(self._tasks, results, strict=True):
                if isinstance(result, Exception):
                    logger.warning(
                        "Background task failed",
                        task_name=task.get_name(),
                        error=str(result),
                    )
        except asyncio.TimeoutError:
            logger.warning(
                "Background tasks timed out, cancelling",
                timeout=timeout,
                pending=sum(1 for t in self._tasks if not t.done()),
            )
            # Cancel remaining tasks
            for task in self._tasks:
                if not task.done():
                    task.cancel()
            # Wait for cancellation to complete
            await asyncio.gather(*self._tasks, return_exceptions=True)


def background_tasks(*, timeout: float = 30.0) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator that injects BackgroundTasks and waits for them on return.
    
    The decorated function must accept a keyword-only `bg_tasks: BackgroundTasks` parameter.
    After the function returns (or raises), all scheduled background tasks are awaited
    with the specified timeout.
    
    Usage:
        @background_tasks(timeout=30)
        async def my_func(..., *, bg_tasks: BackgroundTasks) -> None:
            bg_tasks.run(some_async_operation())
            # ... main logic ...
            # Background tasks are awaited after return
    """

    def decorator(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            bg = BackgroundTasks()
            try:
                return await fn(*args, bg_tasks=bg, **kwargs)  # type: ignore[arg-type]
            finally:
                await bg.wait(timeout=timeout)

        return wrapper

    return decorator
```

### 4g. Create [`backend/app/services/coloring/coloring_generation_service.py`](backend/app/services/coloring/coloring_generation_service.py)

Business logic with SHORT-LIVED locks, state verification, and background Mercure publishes:

```python
"""Coloring generation processing service.

Handles RunPod processing and S3 upload with:
- Short-lived database locks (only during state transitions)
- State verification before each transition (handles race conditions)
- Background Mercure publishes (non-blocking)
- Recovery support (can resume from any intermediate state)
"""

from datetime import UTC, datetime

import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coloring import ColoringVersion
from app.models.enums import ColoringProcessingStatus, RunPodJobStatus
from app.models.order import Image, LineItem, Order
from app.services.coloring.exceptions import UnexpectedStatusError
from app.services.external.runpod import RunPodService
from app.models.enums import VersionType
from app.services.mercure.contexts import ImageStatusContext
from app.services.mercure.publish_service import MercurePublishService
from app.services.storage.paths import OrderStoragePaths
from app.services.storage.storage_service import S3StorageService
from app.tasks.utils.background_tasks import BackgroundTasks
from app.tasks.utils.processing_lock import ProcessingLock, RecordLock

logger = structlog.get_logger(__name__)


class ColoringGenerationService:
    """Service for processing coloring generation via RunPod.
    
    Uses SHORT-LIVED locks with state verification:
    - Lock only during state transitions
    - Verify current status matches expected before updating
    - If status differs, another worker modified it - abort gracefully
    - Mercure publishes are scheduled as background tasks (non-blocking) when bg_tasks provided
    """
    
    def __init__(
        self,
        session: AsyncSession,
        storage: S3StorageService,
        runpod: RunPodService,
        mercure_service: MercurePublishService,
        bg_tasks: BackgroundTasks | None = None,
    ):
        self.session = session
        self.storage = storage
        self.runpod = runpod
        self.mercure_service = mercure_service
        self.bg_tasks = bg_tasks

    async def _verify_and_update(
        self,
        lock: RecordLock[ColoringVersion],
        expected: ColoringProcessingStatus | frozenset[ColoringProcessingStatus],
        new_status: ColoringProcessingStatus,
        **extra_fields: object,
    ) -> ColoringProcessingStatus:
        """Verify current status and update if expected."""
        version = lock.record
        assert version is not None
        
        expected_set = expected if isinstance(expected, frozenset) else frozenset({expected})
        
        if version.status not in expected_set:
            raise UnexpectedStatusError(
                expected=next(iter(expected_set)),
                actual=version.status,
            )
        
        actual = version.status
        await lock.update_record(status=new_status, **extra_fields)
        return actual

    async def process(self, coloring_version_id: int, *, is_recovery: bool = False) -> None:
        """Process a coloring version.
        
        Args:
            coloring_version_id: ID of the ColoringVersion to process
            is_recovery: True if called from recovery.py (affects expected states)
        """
        locker = ProcessingLock(
            self.session,
            ColoringVersion,
            ColoringVersion.id == coloring_version_id,
        )
        
        # === LOCK 1: Check preconditions and mark as PROCESSING ===
        async with locker.acquire() as lock:
            version = lock.record
            assert version is not None
            
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
                current_status = ColoringProcessingStatus.PROCESSING
        
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
        
        assert order.id is not None
        assert image.id is not None
        
        # Create Mercure publishing context (non-blocking if bg_tasks provided)
        mercure = ImageStatusContext(
            service=self.mercure_service,
            bg_tasks=self.bg_tasks,
            order_id=order.id,
            image_id=image.id,
            version_id=coloring_version_id,
            status_type=VersionType.COLORING,
        )
        
        if not image.file_ref:
            raise FileNotFoundError("Image not uploaded to S3 yet")
        
        # Publish current status
        mercure.publish(current_status)
        
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
            
            mercure.publish(ColoringProcessingStatus.RUNPOD_SUBMITTING)
            
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
            
            mercure.publish(ColoringProcessingStatus.RUNPOD_SUBMITTED)
        
        # === OUTSIDE LOCK: Poll RunPod (long-running) ===
        last_known_status = ColoringProcessingStatus.RUNPOD_SUBMITTED
        
        async def on_runpod_status(runpod_status: RunPodJobStatus) -> None:
            nonlocal last_known_status
            
            if runpod_status == RunPodJobStatus.IN_QUEUE:
                new_status = ColoringProcessingStatus.RUNPOD_QUEUED
            elif runpod_status == RunPodJobStatus.IN_PROGRESS:
                new_status = ColoringProcessingStatus.RUNPOD_PROCESSING
            else:
                return
            
            async with locker.acquire() as lock:
                version = lock.record
                assert version is not None
                
                if version.status not in ColoringProcessingStatus.awaiting_external_states():
                    logger.warning(
                        "Status changed unexpectedly during polling",
                        version_id=coloring_version_id,
                        expected=last_known_status.value,
                        actual=version.status.value,
                    )
                    last_known_status = version.status
                    return
                
                await lock.update_record(status=new_status)
                last_known_status = new_status
            
            mercure.publish(new_status)
        
        result_data = await self.runpod.poll_job(job_id, on_status_change=on_runpod_status)
        
        # === LOCK 3: Mark RUNPOD_COMPLETED ===
        async with locker.acquire() as lock:
            try:
                await self._verify_and_update(
                    lock,
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
        
        mercure.publish(ColoringProcessingStatus.RUNPOD_COMPLETED)
        
        # === LOCK 4: Verify RUNPOD_COMPLETED and mark STORAGE_UPLOAD ===
        async with locker.acquire() as lock:
            try:
                await self._verify_and_update(
                    lock,
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
        
        mercure.publish(ColoringProcessingStatus.STORAGE_UPLOAD)
        
        # === OUTSIDE LOCK: Upload to S3 ===
        paths = OrderStoragePaths(order)
        output_key = paths.coloring_version_path(line_item, image, coloring_version_id)
        
        file_ref = await self.storage.upload(
            upload_to=output_key,
            data=result_data,
            content_type="image/png",
        )
        
        # === LOCK 5: Verify STORAGE_UPLOAD and mark COMPLETED ===
        async with locker.acquire() as lock:
            try:
                await self._verify_and_update(
                    lock,
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
            
            image.selected_coloring_id = coloring_version_id
            await self.session.flush()
        
        mercure.publish(ColoringProcessingStatus.COMPLETED)
        
        logger.info("Coloring generation completed", version_id=coloring_version_id, s3_key=output_key)

    async def mark_error(self, coloring_version_id: int) -> None:
        """Mark version as ERROR (called by task on exception)."""
        locker = ProcessingLock(
            self.session,
            ColoringVersion,
            ColoringVersion.id == coloring_version_id,
        )
        try:
            async with locker.acquire() as lock:
                await lock.update_record(status=ColoringProcessingStatus.ERROR)
        except Exception:
            pass  # Best effort
```

### 4h. Simplify [`backend/app/tasks/coloring/generate_coloring.py`](backend/app/tasks/coloring/generate_coloring.py)

Task uses `@background_tasks` decorator for Mercure publishes:

```python
"""Coloring book generation background task."""

import asyncio

import dramatiq
import structlog

from app.services.coloring.coloring_generation_service import ColoringGenerationService
from app.services.coloring.coloring_service import ColoringService
from app.services.external.runpod import RunPodError, RunPodService
from app.services.mercure.publish_service import MercurePublishService
from app.services.storage.storage_service import S3StorageService
from app.tasks.decorators import task_recover
from app.tasks.utils.background_tasks import BackgroundTasks, background_tasks
from app.tasks.utils.processing_lock import RecordLockedError, RecordNotFoundError
from app.tasks.utils.task_db import task_db_session

logger = structlog.get_logger(__name__)


@task_recover(ColoringService.get_incomplete_versions)
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def generate_coloring(coloring_version_id: int, *, is_recovery: bool = False) -> None:
    """Generate a coloring book version for an image."""
    asyncio.run(_generate_coloring_async(coloring_version_id, is_recovery=is_recovery))


@background_tasks(timeout=30)
async def _generate_coloring_async(
    coloring_version_id: int,
    *,
    is_recovery: bool = False,
    bg_tasks: BackgroundTasks,  # Injected by @background_tasks decorator
) -> None:
    """Async implementation - decorator handles bg_tasks injection and cleanup."""
    mercure = MercurePublishService()
    runpod = RunPodService()
    storage = S3StorageService()

    logger.info(
        "Starting coloring generation",
        coloring_version_id=coloring_version_id,
        is_recovery=is_recovery,
    )

    async with task_db_session() as session:
        service = ColoringGenerationService(
            session=session,
            storage=storage,
            runpod=runpod,
            mercure_service=mercure,
            bg_tasks=bg_tasks,
        )
        
        try:
            await service.process(coloring_version_id, is_recovery=is_recovery)
            
        except RecordNotFoundError as e:
            logger.error(str(e), coloring_version_id=coloring_version_id)
            return
            
        except RecordLockedError as e:
            logger.info(str(e), coloring_version_id=coloring_version_id)
            return
            
        except (RunPodError, FileNotFoundError, OSError) as e:
            logger.error(
                "Coloring generation failed",
                coloring_version_id=coloring_version_id,
                error=str(e),
            )
            await service.mark_error(coloring_version_id)
            raise
```

### 4i. Create [`backend/app/services/coloring/svg_generation_service.py`](backend/app/services/coloring/svg_generation_service.py)

Similar pattern with background Mercure publishes:

```python
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

from app.models.coloring import SvgVersion
from app.models.enums import SvgProcessingStatus
from app.models.order import Image, LineItem, Order
from app.services.coloring.exceptions import UnexpectedStatusError
from app.services.external.vectorizer import VectorizerApiService
from app.models.enums import VersionType
from app.services.mercure.contexts import ImageStatusContext
from app.services.mercure.publish_service import MercurePublishService
from app.services.storage.paths import OrderStoragePaths
from app.services.storage.storage_service import S3StorageService
from app.tasks.utils.background_tasks import BackgroundTasks
from app.tasks.utils.processing_lock import ProcessingLock, RecordLock

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

    async def _verify_and_update(
        self,
        lock: RecordLock[SvgVersion],
        expected: SvgProcessingStatus | frozenset[SvgProcessingStatus],
        new_status: SvgProcessingStatus,
        **extra_fields: object,
    ) -> SvgProcessingStatus:
        """Verify current status and update if expected."""
        version = lock.record
        assert version is not None
        
        expected_set = expected if isinstance(expected, frozenset) else frozenset({expected})
        
        if version.status not in expected_set:
            raise UnexpectedStatusError(
                expected=next(iter(expected_set)),
                actual=version.status,
            )
        
        actual = version.status
        await lock.update_record(status=new_status, **extra_fields)
        return actual

    async def process(self, svg_version_id: int, *, is_recovery: bool = False) -> None:
        """Process an SVG version."""
        locker = ProcessingLock(
            self.session,
            SvgVersion,
            SvgVersion.id == svg_version_id,
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
            
            image_id = version.image_id
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
        
        coloring = image.selected_coloring
        if not coloring or not coloring.file_ref:
            raise FileNotFoundError("Coloring version not available")
        
        mercure.publish(current_status)
        
        # === OUTSIDE LOCK: Download coloring ===
        image_data = await self.storage.download(coloring.file_ref)
        
        # === LOCK 2: Verify PROCESSING and mark VECTORIZER_PROCESSING ===
        async with locker.acquire() as lock:
            try:
                await self._verify_and_update(
                    lock,
                    expected=SvgProcessingStatus.PROCESSING,
                    new_status=SvgProcessingStatus.VECTORIZER_PROCESSING,
                )
            except UnexpectedStatusError as e:
                logger.error("Cannot start vectorization", version_id=svg_version_id, actual=e.actual.value)
                return
        
        mercure.publish(SvgProcessingStatus.VECTORIZER_PROCESSING)
        
        # === OUTSIDE LOCK: Vectorize (long-running) ===
        svg_data = await self.vectorizer.vectorize(image_data)
        
        # === LOCK 3: Mark VECTORIZER_COMPLETED ===
        async with locker.acquire() as lock:
            try:
                await self._verify_and_update(
                    lock,
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
                await self._verify_and_update(
                    lock,
                    expected=SvgProcessingStatus.VECTORIZER_COMPLETED,
                    new_status=SvgProcessingStatus.STORAGE_UPLOAD,
                )
            except UnexpectedStatusError as e:
                logger.error("Cannot start upload", version_id=svg_version_id, actual=e.actual.value)
                return
        
        mercure.publish(SvgProcessingStatus.STORAGE_UPLOAD)
        
        # === OUTSIDE LOCK: Upload to S3 ===
        paths = OrderStoragePaths(order)
        output_key = paths.svg_version_path(line_item, image, svg_version_id)
        
        file_ref = await self.storage.upload(
            upload_to=output_key,
            data=svg_data,
            content_type="image/svg+xml",
        )
        
        # === LOCK 5: Mark COMPLETED ===
        async with locker.acquire() as lock:
            try:
                await self._verify_and_update(
                    lock,
                    expected=SvgProcessingStatus.STORAGE_UPLOAD,
                    new_status=SvgProcessingStatus.COMPLETED,
                    file_ref=file_ref,
                    completed_at=datetime.now(UTC),
                )
            except UnexpectedStatusError as e:
                logger.error("Cannot mark COMPLETED", version_id=svg_version_id, actual=e.actual.value)
                return
            
            image.selected_svg_id = svg_version_id
            await self.session.flush()
        
        mercure.publish(SvgProcessingStatus.COMPLETED)
        
        logger.info("SVG generation completed", version_id=svg_version_id, s3_key=output_key)

    async def mark_error(self, svg_version_id: int) -> None:
        """Mark version as ERROR."""
        locker = ProcessingLock(
            self.session,
            SvgVersion,
            SvgVersion.id == svg_version_id,
        )
        try:
            async with locker.acquire() as lock:
                await lock.update_record(status=SvgProcessingStatus.ERROR)
        except Exception:
            pass
```

### 4j. Simplify [`backend/app/tasks/coloring/vectorize_image.py`](backend/app/tasks/coloring/vectorize_image.py)

Same pattern with `@background_tasks` decorator:

```python
"""SVG vectorization background task."""

import asyncio

import dramatiq
import structlog

from app.services.coloring.svg_generation_service import SvgGenerationService
from app.services.coloring.vectorizer_service import VectorizerService
from app.services.external.vectorizer import VectorizerApiService, VectorizerError
from app.services.mercure.publish_service import MercurePublishService
from app.services.storage.storage_service import S3StorageService
from app.tasks.decorators import task_recover
from app.tasks.utils.background_tasks import BackgroundTasks, background_tasks
from app.tasks.utils.processing_lock import RecordLockedError, RecordNotFoundError
from app.tasks.utils.task_db import task_db_session

logger = structlog.get_logger(__name__)


@task_recover(VectorizerService.get_incomplete_versions)
@dramatiq.actor(max_retries=3, min_backoff=1000, max_backoff=60000)
def generate_svg(svg_version_id: int, *, is_recovery: bool = False) -> None:
    """Generate an SVG version from a coloring image."""
    asyncio.run(_generate_svg_async(svg_version_id, is_recovery=is_recovery))


@background_tasks(timeout=30)
async def _generate_svg_async(
    svg_version_id: int,
    *,
    is_recovery: bool = False,
    bg_tasks: BackgroundTasks,  # Injected by @background_tasks decorator
) -> None:
    """Async implementation - decorator handles bg_tasks injection and cleanup."""
    mercure = MercurePublishService()
    vectorizer = VectorizerApiService()
    storage = S3StorageService()

    logger.info(
        "Starting SVG generation",
        svg_version_id=svg_version_id,
        is_recovery=is_recovery,
    )

    async with task_db_session() as session:
        service = SvgGenerationService(
            session=session,
            storage=storage,
            vectorizer=vectorizer,
            mercure_service=mercure,
            bg_tasks=bg_tasks,
        )
        
        try:
            await service.process(svg_version_id, is_recovery=is_recovery)
            
        except RecordNotFoundError as e:
            logger.error(str(e), svg_version_id=svg_version_id)
            return
            
        except RecordLockedError as e:
            logger.info(str(e), svg_version_id=svg_version_id)
            return
            
        except (VectorizerError, FileNotFoundError, OSError) as e:
            logger.error(
                "SVG generation failed",
                svg_version_id=svg_version_id,
                error=str(e),
            )
            await service.mark_error(svg_version_id)
            raise
```

### 4k. Update MercureService imports in order tasks

Update imports in files that use `MercureService`:

**`backend/app/tasks/orders/order_ingestion.py`:**

```python
# OLD
from app.services.external.mercure import MercureService

# NEW
from app.services.mercure.publish_service import MercurePublishService

# Update usage: MercureService() -> MercurePublishService()
```

**`backend/app/tasks/orders/image_download.py`:**

```python
# OLD
from app.services.external.mercure import MercureService

# NEW
from app.services.mercure.publish_service import MercurePublishService

# Update usage: MercureService() -> MercurePublishService()
```

### 4l. Delete old mercure file

After all imports are updated and tasks are working:

```bash
rm backend/app/services/external/mercure.py
```

### 5. Regenerate Frontend SDK

**IMPORTANT**: Must regenerate the SDK before updating frontend files to ensure type safety.

```bash
cd frontend
npm run generate:api
```

This regenerates `src/api/generated/` from the backend OpenAPI schema, ensuring:

- New enum values are available as TypeScript types
- Frontend code can be type-checked against backend changes

### 6. Update Frontend [`frontend/src/types/index.ts`](frontend/src/types/index.ts)

Add new status labels to **both** COLORING and SVG display configs:

```typescript
export const COLORING_STATUS_DISPLAY: Record<string, { label: string; color: string }> = {
  // ... existing statuses ...
  runpod_completed: { label: "Runpod: dokončeno", color: "bg-green-100 text-green-800" },
  storage_upload: { label: "Nahrávání na S3", color: "bg-blue-100 text-blue-800" },
  runpod_cancelled: { label: "Zrušeno", color: "bg-orange-100 text-orange-800" },
};

export const SVG_STATUS_DISPLAY: Record<string, { label: string; color: string }> = {
  // ... existing statuses ...
  vectorizer_completed: { label: "Vectorizer: dokončeno", color: "bg-green-100 text-green-800" },
  storage_upload: { label: "Nahrávání na S3", color: "bg-blue-100 text-blue-800" },
};
```

### 7. Database Migration

```python
def upgrade():
    # Coloring statuses
    op.execute("ALTER TYPE coloringprocessingstatus ADD VALUE 'storage_upload'")
    op.execute("ALTER TYPE coloringprocessingstatus ADD VALUE 'runpod_completed'")
    op.execute("ALTER TYPE coloringprocessingstatus ADD VALUE 'runpod_cancelled'")
    
    # SVG statuses
    op.execute("ALTER TYPE svgprocessingstatus ADD VALUE 'storage_upload'")
    op.execute("ALTER TYPE svgprocessingstatus ADD VALUE 'vectorizer_completed'")
```

### 8. Update [`backend/app/tasks/recovery.py`](backend/app/tasks/recovery.py)

Pass `is_recovery=True` when dispatching recovered tasks:

```python
async def _recover_stuck_tasks() -> int:
    """Find and re-queue tasks that were interrupted mid-processing."""
    total_recovered = 0

    async with async_session_maker() as session:
        for task_fn, get_incomplete_fn in get_recoverable_tasks():
            try:
                version_ids = await get_incomplete_fn(session)
                for version_id in version_ids:
                    logger.info(
                        "Recovering stuck task",
                        task=task_fn.actor_name,
                        version_id=version_id,
                    )
                    # Pass is_recovery=True so service knows to accept intermediate states
                    task_fn.send(version_id, is_recovery=True)
                    total_recovered += 1
            except Exception as e:
                logger.error(
                    "Failed to recover tasks",
                    task=task_fn.actor_name,
                    error=str(e),
                )

    return total_recovered
```

## Usage Examples

```python
# Check status properties via .meta
status = ColoringProcessingStatus.ERROR
status.meta.is_final      # True
status.meta.is_retryable     # True
status.meta.display          # "Chyba"
status.meta.flags            # Flags.FINAL | Flags.RETRYABLE

# Get state sets (for task recovery, locking, etc.)
ColoringProcessingStatus.startable_states()     # {PENDING, QUEUED, ERROR, RUNPOD_CANCELLED}
ColoringProcessingStatus.intermediate_states()  # {QUEUED, PROCESSING, RUNPOD_*, STORAGE_UPLOAD}
ColoringProcessingStatus.final_states()      # {COMPLETED, ERROR, RUNPOD_CANCELLED}
ColoringProcessingStatus.retryable_states()     # {ERROR, RUNPOD_CANCELLED}

# Check flags directly
bool(status.meta.flags & Flags.FINAL)   # True
bool(status.meta.flags & Flags.RETRYABLE)  # True
```

## Invalid Combinations (Caught at Import Time)

```python
# These will raise ValueError when the module is imported:

# FINAL state cannot be recovered by system
BAD = Status("bad", Flags.FINAL | Flags.RECOVERABLE, display="...")
# ValueError: When FINAL: RECOVERABLE cannot be present

# FINAL state cannot be started (it's finished)
BAD = Status("bad", Flags.FINAL | Flags.STARTABLE, display="...")
# ValueError: When FINAL: STARTABLE cannot be present

# FINAL state cannot be awaiting external (it's finished)
BAD = Status("bad", Flags.FINAL | Flags.AWAITING_EXTERNAL, display="...")
# ValueError: When FINAL: AWAITING_EXTERNAL cannot be present

# Only final states can be retried by user
BAD = Status("bad", Flags.RETRYABLE, display="...")
# ValueError: When RETRYABLE: FINAL must be present

# AWAITING_EXTERNAL requires RECOVERABLE (must be able to resume polling)
BAD = Status("bad", Flags.AWAITING_EXTERNAL, display="...")
# ValueError: When AWAITING_EXTERNAL: RECOVERABLE must be present

# AWAITING_EXTERNAL cannot be a starting state (already past start phase)
BAD = Status("bad", Flags.STARTABLE | Flags.AWAITING_EXTERNAL | Flags.RECOVERABLE, display="...")
# ValueError: When AWAITING_EXTERNAL: STARTABLE cannot be present
```

## Defining Custom Rules

```python
# Example: Add a new rule for a hypothetical VERBOSE flag
Flags.RULES.add(
    FlagRule(
        when=Flags.FINAL | Flags.VERBOSE,
        forbidden=Flags.RECOVERABLE,
    )
)
```

## Benefits

1. **Invalid combinations caught early**: Errors raised at module import time
2. **Flexible**: New services can have `FINAL` without `RETRYABLE` (permanent failures)
3. **Explicit**: `Flags.FINAL | Flags.RETRYABLE` is clear about what it means
4. **Extensible**: Easy to add new flags and rules in the future
5. **Declarative**: Rules are data, not code - easy to read and modify

---

## 9. Update Cursor Rules [`backend/.cursor/rules/backend.mdc`](backend/.cursor/rules/backend.mdc)

### Update Service Layer Structure

Update the service folder structure to include mercure and generation services:

```
app/services/
├── exceptions.py
├── download/
│   ├── config.py
│   └── download_service.py
├── orders/
│   ├── exceptions.py
│   ├── order_service.py
│   ├── image_service.py
│   ├── shopify_image_download_service.py
│   └── shopify_sync_service.py
├── coloring/
│   ├── exceptions.py
│   ├── coloring_service.py            # Version management (API-facing)
│   ├── coloring_generation_service.py # Processing logic (task-facing)
│   ├── vectorizer_service.py          # SVG version management (API-facing)
│   └── svg_generation_service.py      # SVG processing logic (task-facing)
├── mercure/                            # NEW: Mercure publishing
│   ├── __init__.py
│   ├── publish_service.py             # MercurePublishService
│   └── contexts.py                    # MercureContext classes
├── storage/
│   ├── storage_service.py
│   └── paths.py
└── external/                           # Third-party API clients
    ├── runpod.py
    ├── shopify.py
    └── vectorizer.py                   # VectorizerApiService
```

Note: `mercure.py` moved from `external/` to its own `mercure/` folder.

### Add new sections for Processing Status and ProcessingLock patterns:

````markdown
## Processing Status Enums (MANDATORY)

Processing status enums MUST extend `ProcessingStatusEnum` and use `Flags` for metadata:

```python
from app.models.status import Flags, ProcessingStatusEnum, Status

class MyProcessingStatus(ProcessingStatusEnum):
    PENDING = Status("pending", Flags.STARTABLE, display="Čeká")
    PROCESSING = Status("processing", Flags.RECOVERABLE, display="Zpracovává se")
    COMPLETED = Status("completed", Flags.FINAL, display="Dokončeno")
    ERROR = Status("error", Flags.FINAL | Flags.RETRYABLE, display="Chyba")
```

### Flag Meanings

| Flag | Meaning |
|------|---------|
| `STARTABLE` | Task can be picked up by a worker (initial states) |
| `RECOVERABLE` | Task recovery should re-dispatch if stuck (active states) |
| `AWAITING_EXTERNAL` | External service processing async (requires polling or webhook) |
| `FINAL` | Final state, no more processing |
| `RETRYABLE` | User can manually retry (requires FINAL) |

### Invalid Combinations (Caught at Import Time)

- `FINAL | RECOVERABLE` - Final states cannot be recovered
- `FINAL | STARTABLE` - Final states cannot be started
- `FINAL | AWAITING_EXTERNAL` - Final states are not waiting for anything
- `RETRYABLE` without `FINAL` - Only final states can be retried
- `AWAITING_EXTERNAL` without `RECOVERABLE` - Must be able to resume polling
- `AWAITING_EXTERNAL | STARTABLE` - Already past start phase

### Accessing Status Metadata

```python
# Single status check
status.meta.is_final         # bool
status.meta.is_retryable     # bool
status.meta.display          # Czech display name

# Get all statuses matching a flag
MyProcessingStatus.startable_states()          # frozenset - STARTABLE or RETRYABLE
MyProcessingStatus.intermediate_states()       # frozenset - RECOVERABLE
MyProcessingStatus.awaiting_external_states()  # frozenset - AWAITING_EXTERNAL
MyProcessingStatus.final_states()              # frozenset - FINAL
MyProcessingStatus.retryable_states()          # frozenset - RETRYABLE
```

### PgEnum Co-location

PostgreSQL enum types MUST be defined in `enums.py` alongside the Python enums:

```python
from sqlalchemy.dialects.postgresql import ENUM as PgEnum

COLORING_STATUS_PG_ENUM = PgEnum(
    ColoringProcessingStatus,
    name="coloringprocessingstatus",
    create_type=False,
    values_callable=lambda e: [member.value for member in e],
)
```

## ProcessingLock Pattern (MANDATORY for Background Tasks)

Background tasks that process database records MUST use `ProcessingLock` with SHORT-LIVED locks:

```python
from app.tasks.utils.processing_lock import ProcessingLock, RecordLockedError, RecordNotFoundError

# Initialize locker (can use direct predicates or predicate_factory)
locker = ProcessingLock(session, MyModel, MyModel.id == record_id)

# Or with multiple predicates (AND-ed together)
locker = ProcessingLock(
    session, MyModel,
    MyModel.id == record_id,
    MyModel.status == MyStatus.PENDING,
)

# === SHORT-LIVED LOCK: Check state and update ===
async with locker.acquire() as lock:
    if lock.record.file_ref is not None:
        await lock.update_record(status=MyStatus.COMPLETED)
        return
    await lock.update_record(status=MyStatus.PROCESSING)

# === OUTSIDE LOCK: Do long-running work ===
result = await external_api.process(...)

# === SHORT-LIVED LOCK: Save result ===
async with locker.acquire() as lock:
    await lock.update_record(file_ref=result, status=MyStatus.COMPLETED)
```

### RecordLock Methods

```python
# Simple field updates
await lock.update_record(
    status=MyStatus.PROCESSING,
    started_at=datetime.utcnow(),
)

# Complex mutations with validation
def start_processing(m: MyModel) -> None:
    if m.status not in startable_states:
        raise ValueError("Invalid state transition")
    m.status = MyStatus.PROCESSING

await lock.mutate_record(start_processing)
```

### Key Points

- **SHORT-LIVED locks** - Hold lock only during state transitions, not during long-running operations
- **Multiple acquires are OK** - Locker is reusable, each `acquire()` is a new transaction
- **Direct predicates preferred** - `MyModel.id == record_id` is clearer than lambda
- **Handle exceptions in TASK** - `RecordNotFoundError` (log error), `RecordLockedError` (log info)
- **Business logic in SERVICES** - Tasks are thin wrappers

### Service Structure

Services receive the record ID and manage their own locking:

```python
class MyGenerationService:
    async def process(self, record_id: int) -> None:
        locker = ProcessingLock(self.session, MyModel, MyModel.id == record_id)
        
        # Lock 1: Check preconditions
        async with locker.acquire() as lock:
            # ... validate and mark PROCESSING ...
        
        # Long-running work (no lock)
        result = await external_api.process(...)
        
        # Lock 2: Save result
        async with locker.acquire() as lock:
            await lock.update_record(file_ref=result, status=COMPLETED)
```

### Task Structure

Tasks delegate to services and handle exceptions:

```python
async with task_db_session() as session:
    service = MyGenerationService(session, ...)
    
    try:
        await service.process(record_id)
    except RecordNotFoundError as e:
        logger.error(str(e))  # Don't retry
        return
    except RecordLockedError as e:
        logger.info(str(e))   # Another worker has it
        return
    except MyProcessingError as e:
        logger.error("Processing failed", error=str(e))
        await service.mark_error(record_id)
        raise  # Let Dramatiq retry
```

## BackgroundTasks Pattern (Mercure Publishes)

Use `@background_tasks` decorator with wrapper pattern for Dramatiq tasks:

```python
from app.tasks.utils.background_tasks import BackgroundTasks, background_tasks

@dramatiq.actor(...)
def my_task(record_id: int, *, is_recovery: bool = False) -> None:
    asyncio.run(_my_task_async(record_id, is_recovery=is_recovery))


@background_tasks(timeout=30)
async def _my_task_async(
    record_id: int,
    *,
    is_recovery: bool = False,
    bg_tasks: BackgroundTasks,  # Injected by @background_tasks decorator
) -> None:
    """Async implementation - decorator handles bg_tasks injection and cleanup."""
    service = MyGenerationService(session, ..., bg_tasks=bg_tasks)
    await service.process(record_id)
```

## MercureContext Pattern (Non-blocking Publishes)

Use `MercureContext` subclasses for repeated publishes with shared context:

```python
from app.models.enums import VersionType
from app.services.mercure.contexts import ImageStatusContext, OrderUpdateContext
from app.services.mercure.publish_service import MercurePublishService

# Create context with shared arguments
mercure = ImageStatusContext(
    service=MercurePublishService(),
    bg_tasks=bg_tasks,       # From @background_tasks decorator
    order_id=order.id,
    image_id=image.id,
    version_id=version.id,
    status_type=VersionType.COLORING,
)

# Non-blocking publish (uses bg_tasks.run())
mercure.publish(ColoringProcessingStatus.PROCESSING)
```

## Service Naming Convention

Two types of services in `services/coloring/`:

| Service | Purpose | Called by |
|---------|---------|-----------|
| `ColoringService` | Version management (create, retry, select) | API routes |
| `ColoringGenerationService` | Processing logic (RunPod, S3 upload) | Dramatiq tasks |
| `VectorizerService` | SVG version management (create, retry) | API routes |
| `SvgGenerationService` | Processing logic (Vectorizer.ai, S3) | Dramatiq tasks |

**Rule**: `*Service` = CRUD/management, `*GenerationService` = background processing.
````