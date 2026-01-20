"""Protocol and decorator for Mercure auto-tracking."""

from collections.abc import Callable
from typing import TYPE_CHECKING, Protocol, TypeVar, runtime_checkable

from sqlalchemy.orm import InstrumentedAttribute

if TYPE_CHECKING:
    from app.db.tracked_session import TrackedAsyncSession
    from app.services.mercure.events import MercureEvent


@runtime_checkable
class MercureTrackable(Protocol):
    """Protocol for services that support Mercure auto-tracking.

    Classes decorated with @mercure_autotrack must have this attribute.
    Enforced at compile-time by mypy/pyright.
    """

    session: "TrackedAsyncSession"


T = TypeVar("T", bound=MercureTrackable)


def mercure_autotrack(
    *event_classes: type["MercureEvent"],
) -> Callable[[type[T]], type[T]]:
    """Class decorator that enables automatic Mercure event tracking.

    Automatically tracks all trigger_fields from the specified event classes.
    Requires the class to have a `session: TrackedAsyncSession` attribute.

    The decorator:
    1. Collects trigger_fields and required_context from all event classes
    2. Wraps __init__ to auto-register field tracking
    3. Sets required context fields for validation

    Usage:
        @mercure_autotrack(ImageUpdateEvent)
        class ColoringGenerationService:
            def __init__(self, session: TrackedAsyncSession, ...):
                self.session = session

            async def process(self, version_id: int, *, order_id: str, image_id: int):
                # MUST call set_mercure_context at the start
                self.session.set_mercure_context(Order.id == order_id, Image.id == image_id)
                # ... any tracked field changes will auto-publish after commit

    Compile-time enforcement:
        If a class decorated with @mercure_autotrack doesn't have
        `session: TrackedAsyncSession`, mypy/pyright will error.

    Dev-time enforcement:
        - set_mercure_context() validates required fields are present
        - Tracked field changes without set_mercure_context() raise MercureContextError
    """

    def decorator(cls: type[T]) -> type[T]:
        # Collect all trigger fields and required context from specified events
        all_trigger_fields: set[InstrumentedAttribute[object]] = set()
        all_required_context: set[InstrumentedAttribute[object]] = set()

        for event_cls in event_classes:
            all_trigger_fields.update(event_cls.trigger_fields)
            all_required_context.update(event_cls.required_context)

        # Convert required_context to field names
        # Order.id -> "order_id", Image.id -> "image_id"
        required_field_names = frozenset(
            f"{attr.class_.__name__.lower()}_id"
            for attr in all_required_context
            if hasattr(attr, "class_") and hasattr(attr, "key") and attr.key == "id"
        )

        # Store on class for introspection
        cls._mercure_events = event_classes  # type: ignore[attr-defined]
        cls._mercure_trigger_fields = frozenset(all_trigger_fields)  # type: ignore[attr-defined]
        cls._mercure_required_context = required_field_names  # type: ignore[attr-defined]

        # Wrap __init__ to auto-register tracking and required context
        original_init = cls.__init__

        def new_init(self: T, *args: object, **kwargs: object) -> None:
            original_init(self, *args, **kwargs)

            # Auto-track all trigger fields and set required context
            if hasattr(self, "session") and all_trigger_fields:
                # Import here to avoid circular imports
                import structlog

                log = structlog.get_logger(__name__)
                log.debug(
                    "mercure_autotrack: setting up tracking",
                    cls=cls.__name__,
                    fields=[f"{f.class_.__name__}.{f.key}" for f in all_trigger_fields],
                )
                self.session.track_changes(*all_trigger_fields)
                # Tell session what context is required for these events
                self.session._set_required_context(required_field_names)

        cls.__init__ = new_init  # type: ignore[method-assign,assignment]
        return cls

    return decorator
