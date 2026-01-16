"""Coloring and SVG vectorization domain exceptions."""

from app.services.exceptions import NotFoundError, ValidationError


class ColoringVersionNotFound(NotFoundError):
    """Coloring version not found."""

    pass


class SvgVersionNotFound(NotFoundError):
    """SVG version not found."""

    pass


class NoColoringAvailable(ValidationError):
    """No completed coloring version available for SVG generation."""

    pass


class VersionNotInErrorState(ValidationError):
    """Version is not in error state, cannot retry."""

    pass


class VersionOwnershipError(ValidationError):
    """Version does not belong to the specified resource."""

    pass


class NoImagesToProcess(ValidationError):
    """No images need processing."""

    pass
