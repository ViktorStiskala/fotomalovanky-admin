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
from app.models.coloring import SvgVersion
from app.services.coloring.exceptions import (
    NoColoringAvailable,
    NoImagesToProcess,
)
from app.services.mercure.events import ImageUpdateEvent
from app.services.orders.exceptions import ImageNotFound, OrderNotFound
from app.tasks.coloring.vectorize_image import generate_svg

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["svg"])


@router.post("/orders/{order_id}/generate-svg", response_model=GenerateSvgResponse, operation_id="generateOrderSvg")
async def generate_order_svg(
    order_id: str,
    service: VectorizerServiceDep,
    request: GenerateSvgRequest | None = None,
) -> GenerateSvgResponse:
    """Generate SVGs for all images in an order that don't have SVG yet."""
    req = request or GenerateSvgRequest()

    try:
        version_ids = await service.create_versions_for_order(
            order_id,
            shape_stacking=req.shape_stacking,
            group_by=req.group_by,
        )

        # Dispatch tasks after DB commit with context for Mercure auto-tracking
        for version_id in version_ids:
            # Get image_id from the version
            version = await service.session.get(SvgVersion, version_id)
            if version:
                generate_svg.send(version_id, order_id=order_id, image_id=version.image_id)

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

        # Get image to find order_id for task dispatch and Mercure event
        image = await image_service.get_image(image_id)
        order_id = image.line_item.order.id

        # Dispatch task after DB commit with context for Mercure auto-tracking
        assert svg_version.id is not None
        generate_svg.send(svg_version.id, order_id=order_id, image_id=image_id)

        # Notify frontend about new queued version
        await mercure.publish(ImageUpdateEvent(order_id=order_id, image_id=image_id))

        return SvgVersionResponse.from_model(svg_version)
    except ImageNotFound:
        raise HTTPException(status_code=404, detail="Image not found")
    except NoColoringAvailable:
        raise HTTPException(
            status_code=400,
            detail="No completed coloring version found. Generate a coloring book first.",
        )
