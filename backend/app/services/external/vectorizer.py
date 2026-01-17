"""Vectorizer.ai API client for SVG conversion."""

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


class VectorizerApiService:
    """Service for vectorizing images to SVG using Vectorizer.ai API.

    This service handles only the API call - file I/O is handled by the caller
    using StorageService for S3 compatibility.
    """

    async def vectorize(
        self,
        image_data: bytes,
        filename: str = "image.png",
        shape_stacking: str = "stacked",
        group_by: str = "color",
    ) -> bytes:
        """Vectorize image data to SVG.

        Args:
            image_data: PNG image bytes to vectorize
            filename: Filename to use in the request (for content-type detection)
            shape_stacking: Shape stacking mode (default: "stacked")
            group_by: Grouping mode (default: "color")

        Returns:
            SVG content as bytes

        Raises:
            VectorizerError: If vectorization fails
            VectorizerBadRequestError: If the request is invalid (HTTP 400)
        """
        # Vectorizer options
        options = {
            "output.shape_stacking": shape_stacking,
            "output.group_by": group_by,
            "output.parameterized_shapes.flatten": "true",
        }

        async with httpx.AsyncClient() as client:
            try:
                files = {"image": (filename, image_data, "image/png")}

                response = await client.post(
                    settings.vectorizer_url,
                    files=files,
                    data=options,
                    auth=(settings.vectorizer_api_key, settings.vectorizer_api_secret),
                    timeout=120.0,  # Vectorization can take a while
                )

                if response.status_code == 200:
                    logger.info("Vectorized image to SVG", size=len(response.content))
                    return response.content
                elif response.status_code == 400:
                    # Bad request - invalid payload, don't retry
                    error_body = response.text[:1000] if response.text else "No response body"
                    logger.error(
                        "Vectorizer API bad request",
                        status_code=response.status_code,
                        response_body=error_body,
                    )
                    raise VectorizerBadRequestError(f"Vectorizer API returned status 400 (bad request): {error_body}")
                else:
                    error_body = response.text[:1000] if response.text else "No response body"
                    logger.error(
                        "Vectorizer API error",
                        status_code=response.status_code,
                        response_body=error_body,
                    )
                    raise VectorizerError(f"Vectorizer API returned status {response.status_code}: {error_body}")

            except httpx.RequestError as e:
                logger.error("Vectorizer request failed", error=str(e))
                raise VectorizerError(f"Request error: {e}") from e
