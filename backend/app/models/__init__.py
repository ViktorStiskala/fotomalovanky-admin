"""Database models."""

# ruff: noqa: I001 - Import order matters for SQLAlchemy relationship resolution
from sqlmodel import SQLModel

from app.models.enums import ImageProcessingStatus, OrderStatus

# order.py must be imported first (defines Image), then coloring.py (references Image)
from app.models.order import Image, LineItem, Order
from app.models.coloring import ColoringVersion, SvgVersion

__all__ = [
    "SQLModel",
    "Order",
    "LineItem",
    "Image",
    "OrderStatus",
    "ImageProcessingStatus",
    "ColoringVersion",
    "SvgVersion",
]
