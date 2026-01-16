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
    """Status of image processing (coloring generation or SVG vectorization)."""

    PENDING = "pending"  # Not yet queued
    QUEUED = "queued"  # Task enqueued
    PROCESSING = "processing"  # Currently processing
    COMPLETED = "completed"  # Successfully completed
    ERROR = "error"  # Processing failed
