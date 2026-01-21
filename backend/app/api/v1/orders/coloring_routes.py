"""Coloring generation API endpoints."""

import structlog
from fastapi import APIRouter, HTTPException

from app.api.v1.orders.dependencies import (
    ColoringServiceDep,
    ImageServiceDep,
    MercureServiceDep,
    VectorizerServiceDep,
)
from app.api.v1.orders.schemas import (
    ColoringVersionResponse,
    GenerateColoringRequest,
    GenerateColoringResponse,
    SvgVersionResponse,
)
from app.models.coloring import ColoringVersion
from app.models.enums import VersionType
from app.services.coloring.exceptions import (
    ColoringVersionNotFound,
    NoImagesToProcess,
    SvgVersionNotFound,
    VersionNotInErrorState,
    VersionOwnershipError,
)
from app.services.mercure.events import ImageUpdateEvent
from app.services.orders.exceptions import (
    ImageNotDownloaded,
    ImageNotFound,
    OrderNotFound,
)
from app.tasks.coloring.generate_coloring import generate_coloring
from app.tasks.coloring.vectorize_image import generate_svg

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["coloring"])


@router.post(
    "/orders/{order_id}/generate-coloring",
    response_model=GenerateColoringResponse,
    operation_id="generateOrderColoring",
)
async def generate_order_coloring(
    order_id: str,
    service: ColoringServiceDep,
    request: GenerateColoringRequest | None = None,
) -> GenerateColoringResponse:
    """Generate coloring books for all images in an order."""
    req = request or GenerateColoringRequest()

    try:
        version_ids = await service.create_versions_for_order(
            order_id,
            megapixels=req.megapixels,
            steps=req.steps,
        )

        # Dispatch tasks after DB commit with context for Mercure auto-tracking
        for version_id in version_ids:
            # Get image_id from the version
            version = await service.session.get(ColoringVersion, version_id)
            if version:
                generate_coloring.send(version_id, order_id=order_id, image_id=version.image_id)

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


@router.post(
    "/images/{image_id}/generate-coloring", response_model=ColoringVersionResponse, operation_id="generateImageColoring"
)
async def generate_image_coloring(
    image_id: int,
    service: ColoringServiceDep,
    image_service: ImageServiceDep,
    mercure: MercureServiceDep,
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

        # Get image to find order_id for task dispatch and Mercure event
        image = await image_service.get_image(image_id)
        order_id = image.line_item.order.id

        # Dispatch task after DB commit with context for Mercure auto-tracking
        assert coloring_version.id is not None
        generate_coloring.send(coloring_version.id, order_id=order_id, image_id=image_id)

        # Notify frontend about new queued version
        await mercure.publish(ImageUpdateEvent(order_id=order_id, image_id=image_id))

        return ColoringVersionResponse.from_model(coloring_version)
    except ImageNotFound:
        raise HTTPException(status_code=404, detail="Image not found")
    except ImageNotDownloaded:
        raise HTTPException(
            status_code=400,
            detail="Image not downloaded yet. Please download the image first.",
        )


@router.post(
    "/images/{image_id}/versions/{version_type}/{version_id}/retry",
    response_model=ColoringVersionResponse | SvgVersionResponse,
    operation_id="retryVersion",
)
async def retry_version(
    image_id: int,
    version_type: VersionType,
    version_id: int,
    coloring_service: ColoringServiceDep,
    vectorizer_service: VectorizerServiceDep,
    image_service: ImageServiceDep,
) -> ColoringVersionResponse | SvgVersionResponse:
    """Retry a failed version generation with the same settings."""
    try:
        # Get image first to find order_id for task dispatch
        image = await image_service.get_image(image_id)
        order_id = image.line_item.order.id

        if version_type == VersionType.COLORING:
            # Ownership validated inside service with lock
            coloring_version = await coloring_service.prepare_retry(
                version_id, order_id=order_id, image_id=image_id
            )
            assert coloring_version.id is not None
            generate_coloring.send(coloring_version.id, order_id=order_id, image_id=image_id)

            # ImageUpdateEvent auto-published via @mercure_autotrack
            return ColoringVersionResponse.from_model(coloring_version)
        else:  # VersionType.SVG
            # Ownership validated inside service with lock
            svg_version = await vectorizer_service.prepare_retry(
                version_id, order_id=order_id, image_id=image_id
            )
            assert svg_version.id is not None
            generate_svg.send(svg_version.id, order_id=order_id, image_id=image_id)

            # ImageUpdateEvent auto-published via @mercure_autotrack
            return SvgVersionResponse.from_model(svg_version)
    except (ColoringVersionNotFound, SvgVersionNotFound):
        raise HTTPException(status_code=404, detail=f"{version_type.capitalize()} version not found")
    except VersionNotInErrorState:
        raise HTTPException(
            status_code=400,
            detail="Can only retry versions with error status",
        )
    except VersionOwnershipError:
        raise HTTPException(
            status_code=400,
            detail="Version does not belong to this image",
        )
