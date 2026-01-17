"""Enum definitions for database models."""

from enum import StrEnum
from typing import Self


class OrderStatus(StrEnum):
    """Status of an order in the processing pipeline."""

    PENDING = "pending"
    DOWNLOADING = "downloading"
    PROCESSING = "processing"
    READY_FOR_REVIEW = "ready_for_review"
    ERROR = "error"


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

    @classmethod
    def intermediate_states(cls) -> frozenset[Self]:
        """States that indicate task was interrupted mid-processing.

        Includes QUEUED because if dramatiq never picks up the task
        (e.g., worker was down, Redis issue), it needs to be re-dispatched.
        """
        return frozenset(
            {
                cls.QUEUED,
                cls.PROCESSING,
                cls.RUNPOD_SUBMITTING,
                cls.RUNPOD_SUBMITTED,
                cls.RUNPOD_QUEUED,
                cls.RUNPOD_PROCESSING,
            }
        )


class VersionType(StrEnum):
    """Type of generated version - used in storage paths and API routes."""

    COLORING = "coloring"
    SVG = "svg"


class SvgProcessingStatus(StrEnum):
    """Status for SVG vectorization (Vectorizer.ai)."""

    PENDING = "pending"
    QUEUED = "queued"
    PROCESSING = "processing"  # Dramatiq task started
    VECTORIZER_PROCESSING = "vectorizer_processing"  # HTTP request in progress
    COMPLETED = "completed"
    ERROR = "error"

    @classmethod
    def intermediate_states(cls) -> frozenset[Self]:
        """States that indicate task was interrupted mid-processing.

        Includes QUEUED because if dramatiq never picks up the task
        (e.g., worker was down, Redis issue), it needs to be re-dispatched.
        """
        return frozenset(
            {
                cls.QUEUED,
                cls.PROCESSING,
                cls.VECTORIZER_PROCESSING,
            }
        )
