"""Mercure event definitions with tracking metadata.

This module defines all Mercure events used for real-time updates to the frontend.
Events are automatically published by TrackedAsyncSession when tracked fields change.
"""

import builtins
from enum import StrEnum
from typing import ClassVar, Self

from pydantic import BaseModel
from sqlalchemy.orm import InstrumentedAttribute

from app.models.coloring import ColoringVersion, SvgVersion
from app.models.order import Image, Order


class MercureEventType(StrEnum):
    """Mercure event types - serializes to string value in JSON."""

    ORDER_UPDATE = "order_update"
    LIST_UPDATE = "list_update"
    IMAGE_UPDATE = "image_update"


# =============================================================================
# Base Classes
# =============================================================================


class BaseMercureEvent(BaseModel):
    """Base class for all Mercure events.

    Defines common interface:
    - type: MercureEventType enum value
    - get_topics(): Returns Mercure topics for publishing
    - identity_key(): Returns unique key for deduplication
    """

    type: MercureEventType

    def get_topics(self) -> list[str]:
        """Return Mercure topics for this event."""
        raise NotImplementedError

    def identity_key(self) -> str:
        """Unique key for deduplication. Override in subclasses.

        When multiple events of the same type are queued for the same entity,
        only the last one (by identity_key) is published. This ensures the
        frontend receives the latest state.
        """
        return f"{self.__class__.__name__}"


class MercureEvent(BaseMercureEvent):
    """Event that can be auto-triggered by model field changes.

    Subclasses define:
    - trigger_fields: ClassVar of fields that trigger this event
    - required_context: ClassVar of fields needed to construct the event
    """

    trigger_fields: ClassVar[frozenset[InstrumentedAttribute[object]]]
    required_context: ClassVar[tuple[InstrumentedAttribute[object], ...]]


class BatchMercureEvent(BaseMercureEvent):
    """Event that collects/batches other events.

    When _flush_mercure_events runs (after commit):
    1. Finds all events matching `collect_events` types
    2. Detects model mutations matching `trigger_models`
    3. Calls `from_collected()` to create the batched event
    4. Publishes batch to its topics (individual events still publish to their topics)
    """

    collect_events: ClassVar[tuple[builtins.type[BaseMercureEvent], ...]] = ()
    trigger_models: ClassVar[tuple[builtins.type, ...]] = ()

    @classmethod
    def from_collected(
        cls,
        events: list[BaseMercureEvent],
        *,
        changed_models: list[builtins.type] | None = None,
    ) -> Self | None:
        """Create batched event from collected events.

        Args:
            events: List of events matching collect_events types
            changed_models: List of model classes that had instances inserted/deleted

        Returns:
            Batched event instance, or None if no batch should be published.
        """
        raise NotImplementedError


# =============================================================================
# Concrete Events
# =============================================================================


class OrderUpdateEvent(MercureEvent):
    """Event for order-level changes (status, metadata).

    Published to order-specific topic only. ListUpdateEvent batches these
    for the "orders" topic.
    """

    type: MercureEventType = MercureEventType.ORDER_UPDATE
    order_id: str

    trigger_fields: ClassVar[frozenset[InstrumentedAttribute[object]]] = frozenset(
        {
            Order.status,  # type: ignore[arg-type]
        }
    )
    required_context: ClassVar[tuple[InstrumentedAttribute[object], ...]] = (Order.id,)  # type: ignore[assignment]

    def get_topics(self) -> list[str]:
        # Only order-specific topic - ListUpdateEvent handles "orders" topic
        return [f"orders/{self.order_id}"]

    def identity_key(self) -> str:
        return f"order_update:{self.order_id}"


class ImageUpdateEvent(MercureEvent):
    """Event for image-level changes (processing status, selection).

    Published to order-specific topic only. Frontend refetches full image data.
    Not batched into ListUpdateEvent (images not shown in list view).
    """

    type: MercureEventType = MercureEventType.IMAGE_UPDATE
    order_id: str
    image_id: int

    trigger_fields: ClassVar[frozenset[InstrumentedAttribute[object]]] = frozenset(
        {
            ColoringVersion.status,  # type: ignore[arg-type]
            SvgVersion.status,  # type: ignore[arg-type]
            Image.selected_coloring_id,  # type: ignore[arg-type]
            Image.selected_svg_id,  # type: ignore[arg-type]
        }
    )
    required_context: ClassVar[tuple[InstrumentedAttribute[object], ...]] = (Order.id, Image.id)  # type: ignore[assignment]

    def get_topics(self) -> list[str]:
        # Only order-specific topic
        return [f"orders/{self.order_id}"]

    def identity_key(self) -> str:
        return f"image_update:{self.order_id}:{self.image_id}"


class ListUpdateEvent(BatchMercureEvent):
    """Batched event for order list updates.

    Collects OrderUpdateEvent instances and publishes once to "orders" topic.
    - order_ids populated -> targeted refresh for specific orders
    - order_ids empty -> full refresh (additions/deletions detected via trigger_models)

    Note: Does NOT collect ImageUpdateEvent (images not shown in list view).
    """

    type: MercureEventType = MercureEventType.LIST_UPDATE
    order_ids: list[str] = []

    # Only collect OrderUpdateEvent - images not shown in list view
    collect_events: ClassVar[tuple[builtins.type[BaseMercureEvent], ...]] = (OrderUpdateEvent,)

    # Emit on Order insert/delete (triggers full refresh)
    trigger_models: ClassVar[tuple[builtins.type, ...]] = (Order,)

    def get_topics(self) -> list[str]:
        return ["orders"]

    def identity_key(self) -> str:
        # Batch events are unique by type (only one ListUpdateEvent per commit)
        return "list_update"

    @classmethod
    def from_collected(
        cls,
        events: list[BaseMercureEvent],
        *,
        changed_models: list[builtins.type] | None = None,
    ) -> Self | None:
        """Create batched list update from collected OrderUpdateEvents.

        Args:
            events: List of OrderUpdateEvent instances
            changed_models: List of model classes that had instances inserted/deleted

        Returns:
            - ListUpdateEvent(order_ids=[]) if Order was inserted/deleted (full refresh)
            - ListUpdateEvent(order_ids=[...]) for targeted refresh
            - None if nothing to update
        """
        # If Order was inserted/deleted, return full refresh (empty order_ids)
        if changed_models and Order in changed_models:
            return cls(order_ids=[])

        # Otherwise, targeted refresh with order_ids from collected events
        order_ids: set[str] = set()
        for event in events:
            if isinstance(event, OrderUpdateEvent):
                order_ids.add(event.order_id)

        if not order_ids:
            return None

        return cls(order_ids=sorted(order_ids))


# =============================================================================
# Registries
# =============================================================================

# Union for API schema exposure
MercureEventUnion = OrderUpdateEvent | ListUpdateEvent | ImageUpdateEvent

# Events with trigger_fields for auto-tracking
EVENT_REGISTRY: list[type[MercureEvent]] = [
    OrderUpdateEvent,
    ImageUpdateEvent,
]

# Batch events for _flush_mercure_events logic
BATCH_EVENT_REGISTRY: list[type[BatchMercureEvent]] = [
    ListUpdateEvent,
]
