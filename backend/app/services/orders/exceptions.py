"""Order domain exceptions."""

from app.services.exceptions import NotFoundError, ValidationError


class OrderNotFound(NotFoundError):
    """Order not found."""

    pass


class ImageNotFound(NotFoundError):
    """Image not found."""

    pass


class ImageNotFoundInOrder(NotFoundError):
    """Image does not belong to the specified order."""

    pass


class ImageNotDownloaded(ValidationError):
    """Image has not been downloaded yet."""

    pass
