"""Vectorizer.ai API client for SVG conversion."""

from pathlib import Path

import anyio
import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


class VectorizerError(Exception):
    """Vectorizer API error."""

    pass


class VectorizerBadRequestError(VectorizerError):
    """Vectorizer API bad request error (HTTP 400).

    This error should not be retried as the payload is invalid.
    """

    pass


async def vectorize_image(
    input_path: Path,
    output_path: Path,
    shape_stacking: str = "stacked",
    group_by: str = "color",
) -> None:
    """
    Vectorize an image to SVG using Vectorizer.ai.

    Args:
        input_path: Path to source PNG image
        output_path: Path to save generated SVG
        shape_stacking: Shape stacking mode (default: "stacked")
        group_by: Grouping mode (default: "color")

    Raises:
        VectorizerError: If vectorization fails
        FileNotFoundError: If input file doesn't exist
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Input image not found: {input_path}")

    # Vectorizer options
    options = {
        "output.shape_stacking": shape_stacking,
        "output.group_by": group_by,
        "output.parameterized_shapes.flatten": "true",
    }

    # Read input file asynchronously
    image_data = await anyio.Path(input_path).read_bytes()

    async with httpx.AsyncClient() as client:
        try:
            files = {"image": (input_path.name, image_data, "image/png")}

            response = await client.post(
                settings.vectorizer_url,
                files=files,
                data=options,
                auth=(settings.vectorizer_api_key, settings.vectorizer_api_secret),
                timeout=120.0,  # Vectorization can take a while
            )

            if response.status_code == 200:
                # Ensure output directory exists
                output_path.parent.mkdir(parents=True, exist_ok=True)

                # Save SVG asynchronously
                await anyio.Path(output_path).write_bytes(response.content)
                logger.info(
                    "Vectorized image to SVG",
                    input_path=str(input_path),
                    output_path=str(output_path),
                )
            elif response.status_code == 400:
                # Bad request - invalid payload, don't retry
                error_body = response.text[:1000] if response.text else "No response body"
                logger.error(
                    "Vectorizer API bad request",
                    status_code=response.status_code,
                    response_body=error_body,
                    input_path=str(input_path),
                )
                raise VectorizerBadRequestError(f"Vectorizer API returned status 400 (bad request): {error_body}")
            else:
                error_body = response.text[:1000] if response.text else "No response body"
                logger.error(
                    "Vectorizer API error",
                    status_code=response.status_code,
                    response_body=error_body,
                    input_path=str(input_path),
                )
                raise VectorizerError(f"Vectorizer API returned status {response.status_code}: {error_body}")

        except httpx.RequestError as e:
            logger.error("Vectorizer request failed", error=str(e))
            raise VectorizerError(f"Request error: {e}") from e
