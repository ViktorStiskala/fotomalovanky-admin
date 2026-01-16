"""Enum definitions for database models."""

from enum import StrEnum


class OrderStatus(StrEnum):
    """Status of an order in the processing pipeline."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    READY_FOR_REVIEW = "ready_for_review"
    ERROR = "error"


class ImageProcessingStatus(StrEnum):
    """Status of image processing (coloring generation or SVG vectorization).

    DEPRECATED: Use ColoringProcessingStatus or SvgProcessingStatus instead.
    Kept for migration compatibility only.
    """

    PENDING = "pending"  # Not yet queued
    QUEUED = "queued"  # Task enqueued
    PROCESSING = "processing"  # Currently processing
    COMPLETED = "completed"  # Successfully completed
    ERROR = "error"  # Processing failed


class ColoringProcessingStatus(StrEnum):
    """Status for coloring generation (RunPod)."""

    PENDING = "pending"  # Not yet queued
    QUEUED = "queued"  # In Dramatiq queue
    PROCESSING = "processing"  # Dramatiq task started
    RUNPOD_SUBMITTING = "runpod_submitting"  # Submitting to RunPod
    RUNPOD_SUBMITTED = "runpod_submitted"  # RunPod accepted job
    RUNPOD_QUEUED = "runpod_queued"  # RunPod: IN_QUEUE
    RUNPOD_PROCESSING = "runpod_processing"  # RunPod: IN_PROGRESS
    COMPLETED = "completed"
    ERROR = "error"


class SvgProcessingStatus(StrEnum):
    """Status for SVG vectorization (Vectorizer.ai)."""

    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"  # Dramatiq task started
    VECTORIZER_PROCESSING = "vectorizer_processing"  # HTTP request in progress
    COMPLETED = "completed"
    ERROR = "error"
