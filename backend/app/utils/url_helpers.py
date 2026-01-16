"""URL generation helpers for API responses."""

from app.config import settings


def file_path_to_url(file_path: str | None) -> str | None:
    """
    Convert local file path to public URL served by nginx.

    Args:
        file_path: Local filesystem path (e.g., "/data/images/42/1/image.jpg")

    Returns:
        Public URL for browser access (e.g., "http://localhost:8081/static/42/1/image.jpg")
        or None if file_path is None
    """
    if not file_path:
        return None

    # Backend stores files at /data/images/... (volume mounted at /data/images)
    # nginx mounts the same volume at /data and serves /static/ from /data/
    # file_path: /data/images/42/1/image.jpg
    # static_url: http://localhost:8081/static
    # result: http://localhost:8081/static/42/1/image.jpg

    # Remove the /data/images/ prefix to get the relative path
    relative_path = file_path.removeprefix("/data/images/")

    return f"{settings.static_url}/{relative_path}"
