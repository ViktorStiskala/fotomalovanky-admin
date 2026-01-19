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
    RUNPOD_PROCESSING = Status(
        "runpod_processing", Flags.RECOVERABLE | Flags.AWAITING_EXTERNAL, display="Runpod: zpracování"
    )
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
    VECTORIZER_PROCESSING = Status(
        "vectorizer_processing", Flags.RECOVERABLE | Flags.AWAITING_EXTERNAL, display="Vectorizer: zpracování"
    )
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
