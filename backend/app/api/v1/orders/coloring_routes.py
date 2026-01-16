"""Coloring generation API endpoints."""

import structlog
from fastapi import APIRouter, HTTPException

from app.api.v1.orders.dependencies import ColoringServiceDep, ImageServiceDep
from app.api.v1.orders.schemas import (
    ColoringVersionResponse,
    GenerateColoringRequest,
    GenerateColoringResponse,
)
from app.services.coloring.exceptions import (
    ColoringVersionNotFound,
    NoImagesToProcess,
    VersionNotInErrorState,
)
from app.services.external.mercure import publish_image_update
from app.services.orders.exceptions import (
    ImageNotDownloaded,
    ImageNotFound,
    OrderNotFound,
)
from app.tasks.process.generate_coloring import generate_coloring

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["coloring"])


@router.post("/orders/{order_number}/generate-coloring", response_model=GenerateColoringResponse)
async def generate_order_coloring(
    order_number: str,
    service: ColoringServiceDep,
    request: GenerateColoringRequest | None = None,
) -> GenerateColoringResponse:
    """Generate coloring books for all images in an order."""
    req = request or GenerateColoringRequest()

    try:
        version_ids = await service.create_versions_for_order(
            order_number,
            megapixels=req.megapixels,
            steps=req.steps,
        )

        # Dispatch tasks after DB commit
        for version_id in version_ids:
            generate_coloring.send(version_id)

        return GenerateColoringResponse(
            queued=len(version_ids),
            message=f"Queued {len(version_ids)} images for coloring generation",
        )
    except OrderNotFound:
        raise HTTPException(status_code=404, detail="Order not found")
    except NoImagesToProcess:
        raise HTTPException(
            status_code=400,
            detail="No images need coloring generation. All images either have coloring or are processing.",
        )


@router.post("/images/{image_id}/generate-coloring", response_model=ColoringVersionResponse)
async def generate_image_coloring(
    image_id: int,
    service: ColoringServiceDep,
    image_service: ImageServiceDep,
    request: GenerateColoringRequest | None = None,
) -> ColoringVersionResponse:
    """Generate a coloring book for a single image."""
    req = request or GenerateColoringRequest()

    try:
        coloring_version = await service.create_version(
            image_id,
            megapixels=req.megapixels,
            steps=req.steps,
        )

        # Dispatch task after DB commit
        assert coloring_version.id is not None
        generate_coloring.send(coloring_version.id)

        # Get image to emit Mercure event
        image = await image_service.get_image(image_id)
        await publish_image_update(image.clean_order_number, image_id)

        return ColoringVersionResponse.from_model(coloring_version)
    except ImageNotFound:
        raise HTTPException(status_code=404, detail="Image not found")
    except ImageNotDownloaded:
        raise HTTPException(
            status_code=400,
            detail="Image not downloaded yet. Please download the image first.",
        )


@router.post("/coloring-versions/{version_id}/retry", response_model=ColoringVersionResponse)
async def retry_coloring_version(
    version_id: int,
    service: ColoringServiceDep,
) -> ColoringVersionResponse:
    """Retry a failed coloring version generation with the same settings."""
    try:
        coloring_version = await service.prepare_retry(version_id)

        # Dispatch task after DB commit
        assert coloring_version.id is not None
        generate_coloring.send(coloring_version.id)

        return ColoringVersionResponse.from_model(coloring_version)
    except ColoringVersionNotFound:
        raise HTTPException(status_code=404, detail="Coloring version not found")
    except VersionNotInErrorState:
        raise HTTPException(
            status_code=400,
            detail="Can only retry versions with error status",
        )
