"""Image and version API endpoints."""

import structlog
from fastapi import APIRouter, HTTPException

from app.api.v1.orders.dependencies import ImageServiceDep, MercureServiceDep
from app.api.v1.orders.schemas import (
    ColoringVersionResponse,
    ImageResponse,
    StatusResponse,
    SvgVersionResponse,
)
from app.services.coloring.exceptions import (
    ColoringVersionNotFound,
    SvgVersionNotFound,
    VersionOwnershipError,
)
from app.services.orders.exceptions import (
    ImageNotFound,
    ImageNotFoundInOrder,
    OrderNotFound,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["images"])


@router.get("/orders/{order_number}/images/{image_id}", response_model=ImageResponse)
async def get_order_image(
    order_number: str,
    image_id: int,
    service: ImageServiceDep,
) -> ImageResponse:
    """Get a single image with all coloring/SVG versions.

    This endpoint is optimized for Mercure image_status events, allowing
    the frontend to fetch only the updated image data instead of the full order.
    """
    try:
        image = await service.get_order_image(order_number=order_number, image_id=image_id)
        return ImageResponse.from_model(image)
    except OrderNotFound:
        raise HTTPException(status_code=404, detail="Order not found")
    except (ImageNotFound, ImageNotFoundInOrder):
        raise HTTPException(status_code=404, detail="Image not found")


@router.get("/images/{image_id}/coloring-versions", response_model=list[ColoringVersionResponse])
async def list_coloring_versions(
    image_id: int,
    service: ImageServiceDep,
) -> list[ColoringVersionResponse]:
    """List all coloring versions for an image."""
    versions = await service.list_coloring_versions(image_id)
    return [ColoringVersionResponse.from_model(v) for v in versions]


@router.get("/images/{image_id}/svg-versions", response_model=list[SvgVersionResponse])
async def list_svg_versions(
    image_id: int,
    service: ImageServiceDep,
) -> list[SvgVersionResponse]:
    """List all SVG versions for an image (across all coloring versions)."""
    versions = await service.list_svg_versions(image_id)
    return [SvgVersionResponse.from_model(v) for v in versions]


@router.put("/images/{image_id}/select-coloring/{version_id}", response_model=StatusResponse)
async def select_coloring_version(
    image_id: int,
    version_id: int,
    service: ImageServiceDep,
    mercure: MercureServiceDep,
) -> StatusResponse:
    """Select a coloring version as the default for an image."""
    try:
        image = await service.select_coloring_version(image_id, version_id)

        # Emit Mercure event for selection change
        logger.info(
            "Emitting selection change event",
            image_id=image_id,
            order_number=image.clean_order_number,
        )
        await mercure.publish_image_update(image.clean_order_number, image_id)

        return StatusResponse(status="ok", message=f"Selected coloring version {version_id}")
    except ImageNotFound:
        raise HTTPException(status_code=404, detail="Image not found")
    except ColoringVersionNotFound:
        raise HTTPException(status_code=404, detail="Coloring version not found")
    except VersionOwnershipError:
        raise HTTPException(status_code=400, detail="Coloring version does not belong to this image")


@router.put("/images/{image_id}/select-svg/{version_id}", response_model=StatusResponse)
async def select_svg_version(
    image_id: int,
    version_id: int,
    service: ImageServiceDep,
    mercure: MercureServiceDep,
) -> StatusResponse:
    """Select an SVG version as the default for an image."""
    try:
        image = await service.select_svg_version(image_id, version_id)

        # Emit Mercure event for selection change
        logger.info(
            "Emitting selection change event",
            image_id=image_id,
            order_number=image.clean_order_number,
        )
        await mercure.publish_image_update(image.clean_order_number, image_id)

        return StatusResponse(status="ok", message=f"Selected SVG version {version_id}")
    except ImageNotFound:
        raise HTTPException(status_code=404, detail="Image not found")
    except SvgVersionNotFound:
        raise HTTPException(status_code=404, detail="SVG version not found")
    except VersionOwnershipError:
        raise HTTPException(status_code=400, detail="SVG version does not belong to this image")
