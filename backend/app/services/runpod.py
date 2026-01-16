"""RunPod API client for coloring book generation."""

import asyncio
import base64
import io
import time
from collections.abc import Awaitable, Callable
from pathlib import Path

import httpx
import structlog
from PIL import Image

from app.config import settings

logger = structlog.get_logger(__name__)


class RunPodError(Exception):
    """RunPod API error."""

    pass


class RunPodTimeoutError(RunPodError):
    """RunPod job timed out."""

    pass


def _get_base_url() -> str:
    """Get the RunPod API base URL for the configured endpoint."""
    return f"{settings.runpod_api_url}/{settings.runpod_endpoint_id}"


def _get_headers() -> dict[str, str]:
    """Get the authorization headers for RunPod API."""
    return {
        "Authorization": f"Bearer {settings.runpod_api_key}",
        "Content-Type": "application/json",
    }


def _ensure_min_resolution(image_data: bytes) -> bytes:
    """
    Ensure image meets minimum resolution. Upscale if needed.

    Args:
        image_data: Original image bytes

    Returns:
        Image bytes (possibly upscaled)
    """
    with Image.open(io.BytesIO(image_data)) as img:
        width, height = img.size
        max_dim = max(width, height)

        if max_dim >= settings.min_image_size:
            # Image is large enough
            return image_data

        # Calculate scale factor to reach minimum size
        scale = settings.min_image_size / max_dim
        new_width = int(width * scale)
        new_height = int(height * scale)

        # Upscale using LANCZOS for quality
        resized = img.resize((new_width, new_height), Image.Resampling.LANCZOS)

        logger.info(
            "Upscaled image for processing",
            original_size=f"{width}x{height}",
            new_size=f"{new_width}x{new_height}",
        )

        # Save as PNG to avoid compression artifacts
        output = io.BytesIO()
        resized.save(output, format="PNG")
        return output.getvalue()


async def submit_job(
    image_data: bytes,
    megapixels: float | None = None,
    steps: int | None = None,
) -> str:
    """
    Submit a coloring generation job to RunPod.

    Args:
        image_data: Image bytes to process
        megapixels: Resolution/detail level (0.5-8)
        steps: Diffusion steps (1-20)

    Returns:
        Job ID for polling

    Raises:
        RunPodError: If submission fails
    """
    # Ensure minimum resolution
    processed_data = _ensure_min_resolution(image_data)
    image_b64 = base64.b64encode(processed_data).decode()

    input_payload: dict[str, str | float | int] = {"image": image_b64}
    if megapixels is not None:
        input_payload["megapixels"] = megapixels
    if steps is not None:
        input_payload["steps"] = steps

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(
                f"{_get_base_url()}/run",
                headers=_get_headers(),
                json={"input": input_payload},
                timeout=30.0,
            )
            response.raise_for_status()
            result = response.json()

            job_id: str | None = result.get("id")
            if not job_id:
                raise RunPodError("No job ID in response")

            logger.info("Submitted RunPod job", job_id=job_id)
            return job_id

        except httpx.HTTPStatusError as e:
            logger.error(
                "RunPod submission failed",
                status_code=e.response.status_code,
                response=e.response.text,
            )
            raise RunPodError(f"HTTP error: {e.response.status_code}") from e
        except httpx.RequestError as e:
            logger.error("RunPod request failed", error=str(e))
            raise RunPodError(f"Request error: {e}") from e


async def poll_job(
    job_id: str,
    on_status_change: Callable[[str], Awaitable[None]] | None = None,
) -> bytes:
    """
    Poll a RunPod job until completion.

    Args:
        job_id: Job ID to poll
        on_status_change: Optional async callback invoked when RunPod status changes.
            Receives the new status string (e.g., "IN_QUEUE", "IN_PROGRESS").

    Returns:
        Generated image bytes

    Raises:
        RunPodError: If job fails
        RunPodTimeoutError: If job times out
    """
    start_time = time.time()
    last_status: str | None = None

    async with httpx.AsyncClient() as client:
        while True:
            elapsed = time.time() - start_time
            if elapsed > settings.runpod_timeout:
                raise RunPodTimeoutError(f"Job {job_id} timed out after {settings.runpod_timeout}s")

            try:
                response = await client.get(
                    f"{_get_base_url()}/status/{job_id}",
                    headers=_get_headers(),
                    timeout=30.0,
                )
                response.raise_for_status()
                result = response.json()

                status = result.get("status")
                logger.debug("RunPod job status", job_id=job_id, status=status)

                # Call callback if status changed
                if on_status_change and status != last_status:
                    last_status = status
                    if status in ("IN_QUEUE", "IN_PROGRESS"):
                        await on_status_change(status)

                if status == "COMPLETED":
                    output = result.get("output", {})
                    # Handle nested output structure
                    if "output" in output:
                        output = output["output"]

                    image_b64 = output.get("image")
                    if not image_b64:
                        raise RunPodError("No image in completed output")

                    execution_time = result.get("executionTime", 0) / 1000
                    logger.info(
                        "RunPod job completed",
                        job_id=job_id,
                        execution_time=f"{execution_time:.2f}s",
                    )
                    return base64.b64decode(image_b64)

                elif status == "FAILED":
                    error = result.get("error", "Unknown error")
                    raise RunPodError(f"Job failed: {error}")

                elif status in ("IN_QUEUE", "IN_PROGRESS"):
                    await asyncio.sleep(settings.runpod_poll_interval)
                else:
                    # Unknown status, keep polling
                    await asyncio.sleep(settings.runpod_poll_interval)

            except httpx.RequestError as e:
                logger.warning("RunPod poll request failed, retrying", error=str(e))
                await asyncio.sleep(settings.runpod_poll_interval)


async def process_image(
    input_path: Path,
    output_path: Path,
    megapixels: float | None = None,
    steps: int | None = None,
) -> None:
    """
    Process an image through RunPod to generate a coloring book version.

    Args:
        input_path: Path to source image
        output_path: Path to save generated coloring book
        megapixels: Resolution/detail level (0.5-8)
        steps: Diffusion steps (1-20)

    Raises:
        RunPodError: If processing fails
        FileNotFoundError: If input file doesn't exist
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input image not found: {input_path}")

    # Read input image
    image_data = input_path.read_bytes()

    # Submit and wait for completion
    job_id = await submit_job(image_data, megapixels=megapixels, steps=steps)
    result_data = await poll_job(job_id)

    # Ensure output directory exists
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Save result
    output_path.write_bytes(result_data)
    logger.info("Saved coloring book", output_path=str(output_path))
