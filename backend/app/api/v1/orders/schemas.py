"""API schemas for orders endpoints."""

from datetime import datetime

from pydantic import BaseModel, field_serializer

from app.models.coloring import ColoringVersion, SvgVersion
from app.models.enums import ColoringProcessingStatus, OrderStatus, SvgProcessingStatus
from app.models.order import Image, LineItem, Order
from app.utils.datetime_utils import to_api_timezone
from app.utils.url_helpers import file_path_to_url

# =============================================================================
# Response Schemas
# =============================================================================


class OrderResponse(BaseModel):
    """Order response schema for list view."""

    id: int
    shopify_id: int
    shopify_order_number: str
    customer_email: str | None
    customer_name: str | None
    payment_status: str | None
    status: OrderStatus
    item_count: int
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        """Serialize datetime to API timezone."""
        localized_dt = to_api_timezone(dt)
        assert localized_dt is not None
        return localized_dt.isoformat()

    @classmethod
    def from_model(cls, order: Order) -> "OrderResponse":
        """Create response from Order model."""
        return cls(
            id=order.id,  # type: ignore[arg-type]
            shopify_id=order.shopify_id,
            shopify_order_number=order.shopify_order_number,
            customer_email=order.customer_email,
            customer_name=order.customer_name,
            payment_status=order.payment_status,
            status=order.status,
            item_count=len(order.line_items),
            created_at=order.created_at,
        )


class ColoringOptionsResponse(BaseModel):
    """Coloring generation options."""

    megapixels: float
    steps: int


class SvgOptionsResponse(BaseModel):
    """SVG generation options."""

    shape_stacking: str
    group_by: str


class ColoringVersionResponse(BaseModel):
    """Coloring version response schema."""

    id: int
    version: int
    url: str | None
    status: ColoringProcessingStatus
    options: ColoringOptionsResponse
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        """Serialize datetime to API timezone."""
        localized_dt = to_api_timezone(dt)
        assert localized_dt is not None
        return localized_dt.isoformat()

    @classmethod
    def from_model(cls, cv: ColoringVersion) -> "ColoringVersionResponse":
        """Create response from ColoringVersion model."""
        return cls(
            id=cv.id,  # type: ignore[arg-type]
            version=cv.version,
            url=file_path_to_url(cv.file_path),
            status=cv.status,
            options=ColoringOptionsResponse(
                megapixels=cv.megapixels,
                steps=cv.steps,
            ),
            created_at=cv.created_at,
        )


class SvgVersionResponse(BaseModel):
    """SVG version response schema."""

    id: int
    version: int
    url: str | None
    status: SvgProcessingStatus
    coloring_version_id: int
    options: SvgOptionsResponse
    created_at: datetime

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        """Serialize datetime to API timezone."""
        localized_dt = to_api_timezone(dt)
        assert localized_dt is not None
        return localized_dt.isoformat()

    @classmethod
    def from_model(cls, sv: SvgVersion) -> "SvgVersionResponse":
        """Create response from SvgVersion model."""
        return cls(
            id=sv.id,  # type: ignore[arg-type]
            version=sv.version,
            url=file_path_to_url(sv.file_path),
            status=sv.status,
            coloring_version_id=sv.coloring_version_id,
            options=SvgOptionsResponse(
                shape_stacking=sv.shape_stacking,
                group_by=sv.group_by,
            ),
            created_at=sv.created_at,
        )


class VersionsResponse(BaseModel):
    """Container for coloring and SVG versions."""

    coloring: list[ColoringVersionResponse]
    svg: list[SvgVersionResponse]


class SelectedVersionIdsResponse(BaseModel):
    """Selected version IDs."""

    coloring: int | None
    svg: int | None


class ImageResponse(BaseModel):
    """Image response schema."""

    id: int
    position: int
    url: str | None
    downloaded_at: datetime | None
    selected_version_ids: SelectedVersionIdsResponse
    versions: VersionsResponse

    @field_serializer("downloaded_at")
    def serialize_downloaded_at(self, dt: datetime | None) -> str | None:
        """Serialize datetime to API timezone."""
        localized_dt = to_api_timezone(dt)
        return localized_dt.isoformat() if localized_dt else None

    @classmethod
    def from_model(cls, img: Image) -> "ImageResponse":
        """Create response from Image model with all versions."""
        # Collect all SVG versions from all coloring versions
        all_svg_versions: list[SvgVersion] = []
        for cv in img.coloring_versions:
            all_svg_versions.extend(cv.svg_versions)

        return cls(
            id=img.id,  # type: ignore[arg-type]
            position=img.position,
            url=file_path_to_url(img.local_path),
            downloaded_at=img.downloaded_at,
            selected_version_ids=SelectedVersionIdsResponse(
                coloring=img.selected_coloring_id,
                svg=img.selected_svg_id,
            ),
            versions=VersionsResponse(
                coloring=[
                    ColoringVersionResponse.from_model(cv)
                    for cv in sorted(img.coloring_versions, key=lambda x: x.version)
                ],
                svg=[
                    SvgVersionResponse.from_model(sv)
                    for sv in sorted(all_svg_versions, key=lambda x: x.version)
                ],
            ),
        )


class LineItemResponse(BaseModel):
    """Line item response schema."""

    id: int
    title: str
    quantity: int
    dedication: str | None
    layout: str | None
    images: list[ImageResponse]

    @classmethod
    def from_model(cls, li: LineItem) -> "LineItemResponse":
        """Create response from LineItem model."""
        return cls(
            id=li.id,  # type: ignore[arg-type]
            title=li.title,
            quantity=li.quantity,
            dedication=li.dedication,
            layout=li.layout,
            images=[
                ImageResponse.from_model(img)
                for img in sorted(li.images, key=lambda x: x.position)
            ],
        )


class OrderDetailResponse(BaseModel):
    """Detailed order response with line items and images."""

    id: int
    shopify_id: int
    shopify_order_number: str
    customer_email: str | None
    customer_name: str | None
    payment_status: str | None
    shipping_method: str | None
    status: OrderStatus
    created_at: datetime
    line_items: list[LineItemResponse]

    @field_serializer("created_at")
    def serialize_created_at(self, dt: datetime) -> str:
        """Serialize datetime to API timezone."""
        localized_dt = to_api_timezone(dt)
        assert localized_dt is not None
        return localized_dt.isoformat()

    @classmethod
    def from_model(cls, order: Order) -> "OrderDetailResponse":
        """Create response from Order model."""
        return cls(
            id=order.id,  # type: ignore[arg-type]
            shopify_id=order.shopify_id,
            shopify_order_number=order.shopify_order_number,
            customer_email=order.customer_email,
            customer_name=order.customer_name,
            payment_status=order.payment_status,
            shipping_method=order.shipping_method,
            status=order.status,
            created_at=order.created_at,
            line_items=[
                LineItemResponse.from_model(li)
                for li in order.line_items
            ],
        )


class OrderListResponse(BaseModel):
    """Order list response schema."""

    orders: list[OrderResponse]
    total: int


# =============================================================================
# Request Schemas
# =============================================================================


class GenerateColoringRequest(BaseModel):
    """Request body for coloring generation."""

    megapixels: float = 1.0
    steps: int = 4


class GenerateSvgRequest(BaseModel):
    """Request body for SVG generation."""

    shape_stacking: str = "stacked"
    group_by: str = "color"


# =============================================================================
# Simple Response Schemas
# =============================================================================


class GenerateColoringResponse(BaseModel):
    """Response for coloring generation."""

    queued: int
    message: str


class GenerateSvgResponse(BaseModel):
    """Response for SVG generation."""

    queued: int
    message: str


class StatusResponse(BaseModel):
    """Simple status response."""

    status: str
    message: str
