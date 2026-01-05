"""Image download and processing service."""

from pathlib import Path

import anyio
import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def get_storage_path(order_id: int, line_item_id: int, position: int, extension: str = "jpg") -> Path:
    """
    Generate a storage path for an image.

    Structure: {storage_path}/{order_id}/{line_item_id}/image_{position}.{ext}
    """
    base = Path(settings.storage_path)
    return base / str(order_id) / str(line_item_id) / f"image_{position}.{extension}"


async def download_image(url: str, order_id: int, line_item_id: int, position: int) -> str | None:
    """
    Download an image from a URL and save it to local storage.

    Args:
        url: Source URL of the image
        order_id: Order ID for path organization
        line_item_id: Line item ID for path organization
        position: Image position (1-4)

    Returns:
        Local file path if successful, None otherwise
    """
    # Determine file extension from URL or default to jpg
    extension = "jpg"
    if "." in url.split("/")[-1]:
        ext = url.split(".")[-1].lower().split("?")[0]
        if ext in ("jpg", "jpeg", "png", "gif", "webp"):
            extension = ext

    local_path = get_storage_path(order_id, line_item_id, position, extension)

    # Create directory if needed
    local_path.parent.mkdir(parents=True, exist_ok=True)

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, timeout=60.0, follow_redirects=True)
            response.raise_for_status()

            # Save to file (using async file I/O)
            await anyio.Path(local_path).write_bytes(response.content)

            logger.info(
                "Downloaded image",
                url=url,
                local_path=str(local_path),
                size=len(response.content),
            )
            return str(local_path)

        except httpx.HTTPStatusError as e:
            logger.error(
                "Image download failed",
                url=url,
                status_code=e.response.status_code,
            )
            return None
        except httpx.RequestError as e:
            logger.error("Image download request failed", url=url, error=str(e))
            return None
        except OSError as e:
            logger.error("Failed to save image", local_path=str(local_path), error=str(e))
            return None
