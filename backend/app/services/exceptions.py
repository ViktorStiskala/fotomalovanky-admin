"""Base service exceptions.

These exceptions are raised by the service layer and should be caught
by the API layer and converted to appropriate HTTP responses.
"""

from enum import Enum


class ServiceError(Exception):
    """Base service exception."""

    pass


class NotFoundError(ServiceError):
    """Resource not found."""

    pass


class ValidationError(ServiceError):
    """Validation error."""

    pass


class UnexpectedStatusError(ServiceError):
    """Status in DB doesn't match expected status - another worker modified it.

    Raised by RecordLock.verify_and_update_status() when the current status
    doesn't match the expected value.
    """

    def __init__(self, expected: frozenset[Enum], actual: Enum):
        self.expected = expected
        self.actual = actual
        expected_names = ", ".join(sorted(e.value for e in expected))
        super().__init__(f"Expected status in ({expected_names}), got {actual.value}")
