"""Base service exceptions.

These exceptions are raised by the service layer and should be caught
by the API layer and converted to appropriate HTTP responses.
"""


class ServiceError(Exception):
    """Base service exception."""

    pass


class NotFoundError(ServiceError):
    """Resource not found."""

    pass


class ValidationError(ServiceError):
    """Validation error."""

    pass
