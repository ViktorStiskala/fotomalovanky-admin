"""Mercure event schemas - shared contract with frontend."""

from typing import Literal

from pydantic import BaseModel


class OrderUpdateEvent(BaseModel):
    """Event sent when an order is updated."""

    type: Literal["order_update"]
    order_id: str  # ULID


class ListUpdateEvent(BaseModel):
    """Event sent when the order list changes."""

    type: Literal["list_update"]


class ImageUpdateEvent(BaseModel):
    """Event sent when image metadata changes (e.g., selection)."""

    type: Literal["image_update"]
    order_id: str  # ULID
    image_id: int


class ImageStatusEvent(BaseModel):
    """Event sent during image processing status changes."""

    type: Literal["image_status"]
    order_id: str  # ULID
    image_id: int
    status_type: Literal["coloring", "svg"]
    version_id: int
    status: str


# Union type for all possible events
MercureEvent = OrderUpdateEvent | ListUpdateEvent | ImageUpdateEvent | ImageStatusEvent
