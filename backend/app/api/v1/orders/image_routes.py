"""Image and version API endpoints."""

import structlog
from fastapi import APIRouter, HTTPException

from app.api.v1.orders.dependencies import ImageServiceDep, MercureServiceDep
from app.api.v1.orders.schemas import (
    ImageResponse,
    StatusResponse,
)
from app.models.enums import VersionType
from app.services.coloring.exceptions import (
    ColoringVersionNotFound,
    SvgVersionNotFound,
    VersionNotCompleted,
    VersionOwnershipError,
)
from app.services.mercure.events import ImageUpdateEvent
from app.services.orders.exceptions import (
    ImageNotFound,
    ImageNotFoundInOrder,
    OrderNotFound,
)

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["images"])


@router.get("/orders/{order_id}/images/{image_id}", response_model=ImageResponse, operation_id="getOrderImage")
async def get_order_image(
    order_id: str,
    image_id: int,
    service: ImageServiceDep,
) -> ImageResponse:
    """Get a single image with all coloring/SVG versions.

    This endpoint is optimized for Mercure image_status events, allowing
    the frontend to fetch only the updated image data instead of the full order.
    """
    try:
        image = await service.get_order_image(order_id=order_id, image_id=image_id)
        return ImageResponse.from_model(image)
    except OrderNotFound:
        raise HTTPException(status_code=404, detail="Order not found")
    except (ImageNotFound, ImageNotFoundInOrder):
        raise HTTPException(status_code=404, detail="Image not found")


@router.put(
    "/images/{image_id}/versions/{version_type}/{version_id}/select",
    response_model=StatusResponse,
    operation_id="selectVersion",
)
async def select_version(
    image_id: int,
    version_type: VersionType,
    version_id: int,
    service: ImageServiceDep,
    mercure: MercureServiceDep,
) -> StatusResponse:
    """Select a version as the default for an image."""
    try:
        if version_type == VersionType.COLORING:
            image = await service.select_coloring_version(image_id, version_id)
        else:  # VersionType.SVG
            image = await service.select_svg_version(image_id, version_id)

        # Notify frontend about selection change
        order_id = image.line_item.order.id
        logger.info(
            "Emitting selection change event",
            image_id=image_id,
            order_id=order_id,
            version_type=version_type,
        )
        await mercure.publish(ImageUpdateEvent(order_id=order_id, image_id=image_id))

        return StatusResponse(status="ok", message=f"Selected {version_type} version {version_id}")
    except ImageNotFound:
        raise HTTPException(status_code=404, detail="Image not found")
    except (ColoringVersionNotFound, SvgVersionNotFound):
        raise HTTPException(status_code=404, detail=f"{version_type.capitalize()} version not found")
    except VersionOwnershipError:
        raise HTTPException(
            status_code=400, detail=f"{version_type.capitalize()} version does not belong to this image"
        )
    except VersionNotCompleted:
        raise HTTPException(
            status_code=400, detail=f"{version_type.capitalize()} version is not completed yet"
        )
