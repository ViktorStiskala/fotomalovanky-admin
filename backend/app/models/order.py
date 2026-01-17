"""Order, LineItem, and Image database models."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Column, DateTime, Enum, ForeignKey, UniqueConstraint
from sqlmodel import Field, Relationship, SQLModel
from ulid import ULID

from app.models.enums import OrderStatus
from app.models.types import S3ObjectRef, S3ObjectRefData, ULIDType

if TYPE_CHECKING:
    from app.models.coloring import ColoringVersion, SvgVersion


def _utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


def _ulid() -> str:
    """Generate a new ULID string."""
    return str(ULID())


class Order(SQLModel, table=True):
    """Order record (Shopify or manual)."""

    __tablename__ = "orders"

    # ULID stored as PostgreSQL UUID
    id: str = Field(
        default_factory=_ulid,
        max_length=26,
        sa_column=Column(ULIDType, primary_key=True),
    )

    # Display order number: "#1270" for Shopify, "#M1000" for manual
    order_number: str = Field(unique=True, index=True)

    # Shopify fields (optional for manual orders)
    shopify_id: int | None = Field(default=None, unique=True, index=True, sa_type=BigInteger)
    shopify_order_number: str | None = Field(default=None, index=True)

    customer_email: str | None = None
    customer_name: str | None = None
    payment_status: str | None = None  # Shopify displayFinancialStatus
    shipping_method: str | None = None  # Shopify shippingLine.title
    status: OrderStatus = Field(
        default=OrderStatus.PENDING,
        sa_column=Column(
            Enum(OrderStatus, values_callable=lambda e: [x.value for x in e], name="orderstatus", create_type=False),
            nullable=False,
        ),
    )
    created_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))

    # Relationships
    line_items: list["LineItem"] = Relationship(back_populates="order")


# Constraint for LineItem position uniqueness per order
LINE_ITEM_POSITION_CONSTRAINT = UniqueConstraint("order_id", "position", name="uq_line_item_order_position")


class LineItem(SQLModel, table=True):
    """Line item within an order (represents one coloring book)."""

    __tablename__ = "line_items"
    __table_args__ = (LINE_ITEM_POSITION_CONSTRAINT,)

    id: int | None = Field(default=None, primary_key=True)
    order_id: str = Field(
        sa_column=Column(ULIDType, ForeignKey("orders.id"), index=True, nullable=False),
    )
    position: int  # Auto-incremented per order using AutoIncrementOnConflict
    shopify_line_item_id: int | None = Field(default=None, unique=True, sa_type=BigInteger)
    title: str
    quantity: int = 1
    dedication: str | None = None  # "Věnování" custom attribute
    layout: str | None = None  # "Rozvržení" custom attribute

    # Relationships
    order: Order = Relationship(back_populates="line_items")
    images: list["Image"] = Relationship(back_populates="line_item")


# Constraint for Image position uniqueness per line item
IMAGE_POSITION_CONSTRAINT = UniqueConstraint("line_item_id", "position", name="uq_image_line_item_position")


class Image(SQLModel, table=True):
    """Customer-uploaded image for a line item."""

    __tablename__ = "images"
    __table_args__ = (IMAGE_POSITION_CONSTRAINT,)

    id: int | None = Field(default=None, primary_key=True)
    line_item_id: int = Field(foreign_key="line_items.id", index=True)
    position: int  # 1-4 for "Fotka 1" through "Fotka 4", auto-incremented
    original_url: str | None = None  # URL from Shopify custom attribute

    # S3 storage reference (replaces local_path)
    file_ref: S3ObjectRefData | None = Field(
        default=None,
        sa_column=Column(S3ObjectRef, nullable=True),
    )
    uploaded_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))

    # Selected versions (FK to coloring_versions and svg_versions)
    selected_coloring_id: int | None = Field(default=None, foreign_key="coloring_versions.id")
    selected_svg_id: int | None = Field(default=None, foreign_key="svg_versions.id")

    # Relationships
    line_item: LineItem = Relationship(back_populates="images")

    # All coloring versions for this image
    # (string annotations required for cross-module SQLAlchemy resolution)
    coloring_versions: list["ColoringVersion"] = Relationship(  # noqa: UP037
        back_populates="image",
        sa_relationship_kwargs={"foreign_keys": "[ColoringVersion.image_id]"},
    )

    # Selected coloring version (nullable relationship)
    selected_coloring: "ColoringVersion" = Relationship(  # noqa: UP037
        sa_relationship_kwargs={
            "foreign_keys": "[Image.selected_coloring_id]",
            "lazy": "joined",
            "uselist": False,
        },
    )

    # Selected SVG version (nullable relationship)
    selected_svg: "SvgVersion" = Relationship(  # noqa: UP037
        sa_relationship_kwargs={
            "foreign_keys": "[Image.selected_svg_id]",
            "lazy": "joined",
            "uselist": False,
        },
    )
