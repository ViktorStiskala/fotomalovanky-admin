"""Order, LineItem, and Image database models."""

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from sqlalchemy import BigInteger, Column, DateTime
from sqlmodel import Field, Relationship, SQLModel

from app.models.enums import OrderStatus

if TYPE_CHECKING:
    from app.models.coloring import ColoringVersion, SvgVersion


def _utc_now() -> datetime:
    """Return current UTC datetime (timezone-aware)."""
    return datetime.now(UTC)


class Order(SQLModel, table=True):
    """Shopify order record."""

    __tablename__ = "orders"

    id: int | None = Field(default=None, primary_key=True)
    shopify_id: int = Field(unique=True, index=True, sa_type=BigInteger)
    shopify_order_number: str = Field(index=True)
    customer_email: str | None = None
    customer_name: str | None = None
    payment_status: str | None = None  # Shopify displayFinancialStatus
    shipping_method: str | None = None  # Shopify shippingLine.title
    status: OrderStatus = Field(default=OrderStatus.PENDING)
    created_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))
    updated_at: datetime = Field(default_factory=_utc_now, sa_column=Column(DateTime(timezone=True), nullable=False))

    # Relationships
    line_items: list[LineItem] = Relationship(back_populates="order")


class LineItem(SQLModel, table=True):
    """Line item within an order (represents one coloring book)."""

    __tablename__ = "line_items"

    id: int | None = Field(default=None, primary_key=True)
    order_id: int = Field(foreign_key="orders.id", index=True)
    shopify_line_item_id: int = Field(unique=True, sa_type=BigInteger)
    title: str
    quantity: int = 1
    dedication: str | None = None  # "Věnování" custom attribute
    layout: str | None = None  # "Rozvržení" custom attribute

    # Relationships
    order: Order = Relationship(back_populates="line_items")
    images: list[Image] = Relationship(back_populates="line_item")


class Image(SQLModel, table=True):
    """Customer-uploaded image for a line item."""

    __tablename__ = "images"

    id: int | None = Field(default=None, primary_key=True)
    line_item_id: int = Field(foreign_key="line_items.id", index=True)
    position: int  # 1-4 for "Fotka 1" through "Fotka 4"
    original_url: str  # URL from Shopify custom attribute
    local_path: str | None = None  # Path after download
    downloaded_at: datetime | None = Field(default=None, sa_column=Column(DateTime(timezone=True)))

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
