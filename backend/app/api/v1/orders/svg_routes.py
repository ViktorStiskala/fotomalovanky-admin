"""SVG generation API endpoints."""

import structlog
from fastapi import APIRouter, HTTPException

from app.api.v1.orders.dependencies import (
    ImageServiceDep,
    MercureServiceDep,
    VectorizerServiceDep,
)
from app.api.v1.orders.schemas import (
    GenerateSvgRequest,
    GenerateSvgResponse,
    SvgVersionResponse,
)
from app.services.coloring.exceptions import (
    NoColoringAvailable,
    NoImagesToProcess,
    SvgVersionNotFound,
    VersionNotInErrorState,
)
from app.services.orders.exceptions import ImageNotFound, OrderNotFound
from app.tasks.coloring.vectorize_image import vectorize_image

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["svg"])


@router.post("/orders/{shopify_id}/generate-svg", response_model=GenerateSvgResponse, operation_id="generateOrderSvg")
async def generate_order_svg(
    shopify_id: int,
    service: VectorizerServiceDep,
    request: GenerateSvgRequest | None = None,
) -> GenerateSvgResponse:
    """Generate SVGs for all images in an order that don't have SVG yet."""
    req = request or GenerateSvgRequest()

    try:
        version_ids = await service.create_versions_for_order(
            shopify_id,
            shape_stacking=req.shape_stacking,
            group_by=req.group_by,
        )

        # Dispatch tasks after DB commit
        for version_id in version_ids:
            vectorize_image.send(version_id)

        return GenerateSvgResponse(
            queued=len(version_ids),
            message=f"Queued {len(version_ids)} images for SVG generation",
        )
    except OrderNotFound:
        raise HTTPException(status_code=404, detail="Order not found")
    except NoImagesToProcess:
        raise HTTPException(
            status_code=400,
            detail="No images need SVG generation. All images either have SVG, are processing, or have no coloring.",
        )


@router.post("/images/{image_id}/generate-svg", response_model=SvgVersionResponse, operation_id="generateImageSvg")
async def generate_image_svg(
    image_id: int,
    service: VectorizerServiceDep,
    image_service: ImageServiceDep,
    mercure: MercureServiceDep,
    request: GenerateSvgRequest | None = None,
) -> SvgVersionResponse:
    """Generate an SVG for a single image from its selected coloring version."""
    req = request or GenerateSvgRequest()

    try:
        svg_version = await service.create_version(
            image_id,
            shape_stacking=req.shape_stacking,
            group_by=req.group_by,
        )

        # Dispatch task after DB commit
        assert svg_version.id is not None
        vectorize_image.send(svg_version.id)

        # Get image to emit Mercure event
        image = await image_service.get_image(image_id)
        await mercure.publish_image_update(image.line_item.order.shopify_id, image_id)

        return SvgVersionResponse.from_model(svg_version)
    except ImageNotFound:
        raise HTTPException(status_code=404, detail="Image not found")
    except NoColoringAvailable:
        raise HTTPException(
            status_code=400,
            detail="No completed coloring version found. Generate a coloring book first.",
        )


@router.post("/svg-versions/{version_id}/retry", response_model=SvgVersionResponse, operation_id="retrySvgVersion")
async def retry_svg_version(
    version_id: int,
    service: VectorizerServiceDep,
) -> SvgVersionResponse:
    """Retry a failed SVG version generation with the same settings."""
    try:
        svg_version = await service.prepare_retry(version_id)

        # Dispatch task after DB commit
        assert svg_version.id is not None
        vectorize_image.send(svg_version.id)

        return SvgVersionResponse.from_model(svg_version)
    except SvgVersionNotFound:
        raise HTTPException(status_code=404, detail="SVG version not found")
    except VersionNotInErrorState:
        raise HTTPException(
            status_code=400,
            detail="Can only retry versions with error status",
        )
