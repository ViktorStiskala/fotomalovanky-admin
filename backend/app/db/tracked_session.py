"""TrackedAsyncSession with automatic Mercure event publishing."""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import TYPE_CHECKING, Any, Self

import structlog
from sqlalchemy import event
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import InstrumentedAttribute, object_session
from sqlalchemy.sql.elements import BinaryExpression, ColumnElement

from app.db.exceptions import MercureContextError

if TYPE_CHECKING:
    from app.services.mercure.events import BaseMercureEvent, MercureEvent
    from app.services.mercure.publish_service import MercurePublishService
    from app.tasks.utils.background_tasks import BackgroundTasks

logger = structlog.get_logger(__name__)

# Module-level set to track which fields have had listeners registered globally
# This prevents duplicate listener registration across sessions
_GLOBALLY_REGISTERED_FIELDS: set[InstrumentedAttribute[object]] = set()


class TrackedAsyncSession(AsyncSession):
    """AsyncSession with automatic Mercure event tracking.

    This session extension:
    - Tracks specified model field changes via SQLAlchemy listeners
    - Collects events during after_flush_postexec hook
    - Publishes events only after commit() succeeds
    - Deduplicates events by identity_key() (last one wins)
    - Tracks model insert/delete for BatchMercureEvent.trigger_models

    Usage:
        # Services decorated with @mercure_autotrack automatically call _track_changes
        session.set_mercure_context(Order.id == order_id, Image.id == image_id)
        # ... make changes ...
        await session.commit()  # Events published automatically
    """

    # Injected by task_db_session or API dependency
    _bg_tasks: "BackgroundTasks | None" = None
    _mercure_service: "MercurePublishService | None" = None

    # Tracking state
    _tracked_fields: set[InstrumentedAttribute[object]]
    _context_predicates: list[ColumnElement[bool]]
    _pending_changes: set[InstrumentedAttribute[object]]
    _pending_events: list["BaseMercureEvent"]
    _mutated_models: set[type]  # Model classes that had instances inserted/deleted

    # Context validation
    _context_set: bool
    _required_context_fields: frozenset[str]

    # Event deferral state (for batching across multiple commits)
    _defer_mercure_events: bool
    _deferred_events: list["BaseMercureEvent"]
    _deferred_mutated_models: set[type]

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self._tracked_fields = set()
        self._context_predicates = []
        self._pending_changes = set()
        self._pending_events = []
        self._mutated_models = set()
        self._context_set = False
        self._required_context_fields = frozenset()

        # Event deferral state (for batching across multiple commits)
        self._defer_mercure_events = False
        self._deferred_events = []
        self._deferred_mutated_models = set()

        # Store back-reference from sync_session to this async session
        # This is needed because object_session(target) returns the sync session,
        # but we need to access the TrackedAsyncSession for event tracking
        self.sync_session._tracked_async_session = self  # type: ignore[attr-defined]

        # Register the after_flush_postexec listener for this session
        event.listen(self.sync_session, "after_flush_postexec", self._after_flush_postexec)

    def _track_changes(self, *fields: InstrumentedAttribute[object]) -> Self:
        """Internal method - register fields to watch for changes.

        Note: Only called by @mercure_autotrack decorator. Do not call directly.
        """
        global _GLOBALLY_REGISTERED_FIELDS
        for field in fields:
            # Track locally for this session
            self._tracked_fields.add(field)

            # Only register ONE global listener per field (across all sessions)
            if field not in _GLOBALLY_REGISTERED_FIELDS:
                _GLOBALLY_REGISTERED_FIELDS.add(field)
                # Register listener for this field's "set" event
                # Use the class method which dispatches to the correct session
                event.listen(field, "set", TrackedAsyncSession._on_field_change_static, propagate=True)
                logger.debug(
                    "Registered change listener",
                    field=f"{field.class_.__name__}.{field.key}",
                )
        return self

    def _set_required_context(self, required_fields: frozenset[str]) -> None:
        """Set required context fields. Called by @mercure_autotrack decorator.

        These fields will be validated when set_mercure_context() is called.
        """
        self._required_context_fields = required_fields

    def set_mercure_context(self, *predicates: ColumnElement[bool]) -> Self:
        """Set context for Mercure event publishing. Must be called at start of service methods.

        Args:
            *predicates: SQLAlchemy predicates like Order.id == order_id, Image.id == image_id

        Raises:
            MercureContextError: If required context fields cannot be extracted from predicates

        Usage:
            session.set_mercure_context(Order.id == order_id, Image.id == image_id)
        """
        self._context_predicates.extend(predicates)
        self._context_set = True

        # Validate required context is present (required fields set by decorator)
        if self._required_context_fields:
            context = self._extract_context()
            missing = self._required_context_fields - set(context.keys())
            if missing:
                hint = ", ".join(f"{f.replace('_id', '').title()}.id == value" for f in sorted(missing))
                raise MercureContextError(
                    f"Required Mercure context fields missing: {missing}. Ensure predicates include: {hint}"
                )
        return self

    def _start_deferring_events(self) -> Self:
        """Start deferring Mercure event publishing until flush_deferred_events() is called.

        When deferral is enabled, events are collected across multiple commits
        instead of being published immediately after each commit. This is useful
        for bulk operations where you want to batch events into a single publish.

        This is a private method. Use the `deferred_events()` context manager instead.

        Returns:
            Self for method chaining.
        """
        self._defer_mercure_events = True
        return self

    @asynccontextmanager
    async def deferred_batch_events(self) -> AsyncIterator[Self]:
        """Context manager for deferring batch events with automatic flush/cleanup.

        Only defers events that are collected by a BatchMercureEvent (e.g., OrderUpdateEvent
        is collected by ListUpdateEvent). Non-collected events (e.g., ImageUpdateEvent)
        publish immediately even during deferral.

        When the context exits successfully, deferred events are published as a single
        batched message. If an exception occurs, deferred events are discarded.

        Usage:
            async with session.deferred_batch_events():
                # Multiple commits happen here
                for item in items:
                    await service.process(item)  # Each may commit
            # Single batched ListUpdateEvent published here

        Yields:
            Self for method chaining if needed.
        """
        self._start_deferring_events()
        try:
            yield self
            await self.flush_deferred_events()
        except BaseException:
            # Clear deferred events on error - don't publish partial updates
            self._deferred_events.clear()
            self._deferred_mutated_models.clear()
            self._defer_mercure_events = False
            raise

    async def flush_deferred_events(self) -> None:
        """Publish all deferred events as a single batch.

        This method processes all events collected during deferral:
        1. Deduplicates events by identity_key() (last one wins)
        2. Creates batch events from collected events (e.g., ListUpdateEvent)
        3. Publishes all events

        Called automatically by the `deferred_events()` context manager.
        """
        self._defer_mercure_events = False

        if not self._deferred_events and not self._deferred_mutated_models:
            return

        if not self._mercure_service:
            logger.debug("No Mercure service configured, skipping deferred event publish")
            self._deferred_events.clear()
            self._deferred_mutated_models.clear()
            return

        # Import here to avoid circular imports
        from app.services.mercure.events import BATCH_EVENT_REGISTRY

        # Deduplicate by identity_key (last wins - ensures latest state)
        seen: dict[str, "BaseMercureEvent"] = {}
        for deferred_event in self._deferred_events:
            seen[deferred_event.identity_key()] = deferred_event

        events_to_publish: list["BaseMercureEvent"] = list(seen.values())

        # Create batch events from collected events
        for batch_cls in BATCH_EVENT_REGISTRY:
            # Find events that should be collected by this batch type
            collected = [e for e in events_to_publish if type(e) in batch_cls.collect_events]

            # Find model mutations relevant to this batch type
            changed_models = [m for m in batch_cls.trigger_models if m in self._deferred_mutated_models]

            # Create batch event if there are collected events OR model mutations
            if collected or changed_models:
                batch_event = batch_cls.from_collected(collected, changed_models=changed_models)
                if batch_event is not None:
                    events_to_publish.append(batch_event)

        logger.debug(
            "Publishing deferred Mercure events",
            event_count=len(events_to_publish),
            event_types=[type(e).__name__ for e in events_to_publish],
        )

        # Publish all events
        coros = [self._mercure_service.publish(e) for e in events_to_publish]

        if self._bg_tasks:
            # Non-blocking: schedule via BackgroundTasks
            for coro in coros:
                self._bg_tasks.run(coro)
        else:
            # Blocking: await all directly
            await asyncio.gather(*coros, return_exceptions=True)

        # Clear state
        self._deferred_events.clear()
        self._deferred_mutated_models.clear()

    @staticmethod
    def _on_field_change_static(target: Any, value: Any, oldvalue: Any, initiator: Any) -> None:
        """SQLAlchemy attribute listener for tracked field changes (static method).

        This is registered ONCE per field globally (not per session) and dispatches
        to the correct TrackedAsyncSession via object_session(target).
        """
        if value == oldvalue:
            return

        # Get field name for logging/error messages
        field_name = f"{type(target).__name__}.{initiator.key}"

        # Get the session for this target object
        # object_session returns the sync session, so we need to get our async wrapper
        sync_session = object_session(target)
        if sync_session is None:
            logger.debug("Field change ignored - no session", field=field_name)
            return

        # Get the TrackedAsyncSession back-reference we stored on the sync session
        tracked_session: TrackedAsyncSession | None = getattr(sync_session, "_tracked_async_session", None)

        if tracked_session is None:
            logger.debug(
                "Field change ignored - no TrackedAsyncSession back-reference",
                field=field_name,
                session_type=type(sync_session).__name__,
            )
            return

        # Check if this session is actually tracking this field
        # (session may not have called _track_changes for this field)
        field_tracked = any(
            f.key == initiator.key and f.class_ is type(target)
            for f in tracked_session._tracked_fields
        )
        if not field_tracked:
            return  # This session isn't tracking this field

        # Protection: Error if tracked field changes without context being set
        if not tracked_session._context_set:
            raise MercureContextError(
                f"Tracked field '{field_name}' changed but set_mercure_context() was not called. "
                f"Call session.set_mercure_context(Order.id == order_id, ...) at the start of your method."
            )

        # Safely convert values for logging (oldvalue can be NEVER_SET constant)
        try:
            old_str = str(oldvalue)[:50] if oldvalue is not None else None
        except Exception:
            old_str = repr(type(oldvalue))
        try:
            new_str = str(value)[:50] if value is not None else None
        except Exception:
            new_str = repr(type(value))

        # Find the matching InstrumentedAttribute from tracked_fields
        # (initiator.key is just the attribute name string)
        matching_field = None
        for tracked_field in tracked_session._tracked_fields:
            if tracked_field.key == initiator.key and tracked_field.class_ is type(target):
                matching_field = tracked_field
                break

        if matching_field is None:
            logger.warning(
                "Could not find matching tracked field",
                field=field_name,
                tracked_fields=[f"{f.class_.__name__}.{f.key}" for f in tracked_session._tracked_fields],
            )
            return

        logger.debug(
            "Tracked field change detected",
            field=field_name,
            old_value=old_str,
            new_value=new_str,
        )
        tracked_session._pending_changes.add(matching_field)

    def _extract_context(self) -> dict[str, Any]:
        """Extract context values from predicates like Order.id == 'abc'.

        Returns:
            Dictionary mapping field names to values, e.g., {"order_id": "abc", "image_id": 123}
        """
        context: dict[str, Any] = {}

        for predicate in self._context_predicates:
            if isinstance(predicate, BinaryExpression):
                # Extract column and value from BinaryExpression (e.g., Order.id == 'abc')
                left = predicate.left
                right = predicate.right

                # Get the value from the right side
                if hasattr(right, "value"):
                    val = right.value
                else:
                    val = right

                # Map to event field name (Order.id -> order_id, Image.id -> image_id)
                # After comparison, left becomes AnnotatedColumn with table.name (e.g., "orders", "images")
                if hasattr(left, "table") and hasattr(left, "name"):
                    col_name: str = left.name
                    if col_name == "id":
                        # Convert plural table name to singular (orders -> order, images -> image)
                        table_name: str = left.table.name
                        singular = table_name.rstrip("s")  # Simple pluralization for our models
                        context[f"{singular}_id"] = val
                    else:
                        context[col_name] = val

        return context

    def _after_flush_postexec(self, session: Any, flush_context: Any) -> None:
        """Called after flush completes. Queue events for publishing after commit.

        Uses after_flush_postexec (not after_flush) to see final session.new/session.deleted state.
        """
        # Import here to avoid circular imports
        from app.services.mercure.events import BATCH_EVENT_REGISTRY, EVENT_REGISTRY

        logger.debug(
            "after_flush_postexec called",
            pending_changes=len(self._pending_changes),
            pending_events=len(self._pending_events),
        )

        # Track model mutations (inserts/deletes) for BatchMercureEvent.trigger_models
        all_trigger_models: set[type] = set()
        for batch_cls in BATCH_EVENT_REGISTRY:
            all_trigger_models.update(batch_cls.trigger_models)

        for obj in session.new:
            obj_type = type(obj)
            if obj_type in all_trigger_models:
                self._mutated_models.add(obj_type)

        for obj in session.deleted:
            obj_type = type(obj)
            if obj_type in all_trigger_models:
                self._mutated_models.add(obj_type)

        # Process pending field changes into events
        if not self._pending_changes:
            logger.debug("No pending changes to process")
            return

        logger.debug(
            "Processing pending changes",
            changes=[f"{f.class_.__name__}.{f.key}" for f in self._pending_changes],
        )

        # Find which event types to dispatch based on changed fields
        events_to_queue: set[type["MercureEvent"]] = set()

        for changed_field in self._pending_changes:
            for event_cls in EVENT_REGISTRY:
                if changed_field in event_cls.trigger_fields:
                    events_to_queue.add(event_cls)

        logger.debug("Events to queue", events=[e.__name__ for e in events_to_queue])

        # Queue events for publishing
        for event_cls in events_to_queue:
            self._schedule_event_publish(event_cls)

        self._pending_changes.clear()

    def _schedule_event_publish(self, event_cls: type["MercureEvent"]) -> None:
        """Extract context from predicates and queue event for publishing."""
        # Extract context directly from predicates
        context = self._extract_context()

        # Build kwargs for event constructor
        # Map required_context attributes to context keys
        event_kwargs: dict[str, Any] = {}
        for attr in event_cls.required_context:
            # attr is like Order.id -> we need "order_id"
            if hasattr(attr, "class_") and hasattr(attr, "key"):
                if attr.key == "id":
                    key = f"{attr.class_.__name__.lower()}_id"
                else:
                    key = attr.key

                if key in context:
                    event_kwargs[key] = context[key]
                else:
                    logger.warning(
                        "Cannot publish event - incomplete context",
                        event_type=event_cls.__name__,
                        missing_key=key,
                    )
                    return

        # Construct event instance and queue for publishing
        event_instance = event_cls(**event_kwargs)
        self._pending_events.append(event_instance)

    async def commit(self) -> None:
        """Commit transaction and publish Mercure events.

        Events are collected during after_flush hooks, but only published
        AFTER commit to ensure frontend sees committed data.
        """
        logger.debug(
            "TrackedAsyncSession.commit() called",
            pending_events=len(self._pending_events),
            has_mercure_service=self._mercure_service is not None,
        )
        await super().commit()
        await self._flush_mercure_events()

    async def _flush_mercure_events(self) -> None:
        """Publish all pending Mercure events with automatic batching.

        Called automatically by commit(). Do not call directly.

        1. If deferral is enabled, defers only events collected by BatchMercureEvent
        2. Non-collected events (e.g., ImageUpdateEvent) publish immediately
        3. Deduplicates events by identity_key() (last one wins)
        4. Creates batch events from collected events via BATCH_EVENT_REGISTRY
        5. Uses bg_tasks if available, otherwise asyncio.gather
        """
        if not self._pending_events and not self._mutated_models:
            return

        # Import here to avoid circular imports
        from app.services.mercure.events import BATCH_EVENT_REGISTRY

        # If deferral is enabled, only defer events that are collected by BatchMercureEvent
        # Non-collected events (like ImageUpdateEvent) should publish immediately
        if self._defer_mercure_events:
            # Build set of event types that are collected by any batch event
            collected_types: set[type] = set()
            for batch_cls in BATCH_EVENT_REGISTRY:
                collected_types.update(batch_cls.collect_events)

            # Split events: defer collected ones, publish non-collected immediately
            events_to_defer: list["BaseMercureEvent"] = []
            events_to_publish_now: list["BaseMercureEvent"] = []

            for event in self._pending_events:
                if type(event) in collected_types:
                    events_to_defer.append(event)
                else:
                    events_to_publish_now.append(event)

            # Defer collected events and model mutations
            self._deferred_events.extend(events_to_defer)
            self._deferred_mutated_models.update(self._mutated_models)
            self._pending_events.clear()
            self._mutated_models.clear()

            if events_to_defer:
                logger.debug(
                    "Deferring Mercure events",
                    deferred_count=len(self._deferred_events),
                    deferred_models=len(self._deferred_mutated_models),
                )

            # Publish non-collected events immediately (if any)
            if events_to_publish_now and self._mercure_service:
                logger.debug(
                    "Publishing non-deferred events immediately",
                    event_count=len(events_to_publish_now),
                    event_types=[type(e).__name__ for e in events_to_publish_now],
                )
                coros = [self._mercure_service.publish(e) for e in events_to_publish_now]
                if self._bg_tasks:
                    for coro in coros:
                        self._bg_tasks.run(coro)
                else:
                    await asyncio.gather(*coros, return_exceptions=True)
            return

        if not self._mercure_service:
            logger.debug("No Mercure service configured, skipping event publish")
            self._pending_events.clear()
            self._mutated_models.clear()
            return

        # Deduplicate by identity_key (last wins - ensures latest state)
        seen: dict[str, "BaseMercureEvent"] = {}
        for pending_event in self._pending_events:
            seen[pending_event.identity_key()] = pending_event

        events_to_publish: list["BaseMercureEvent"] = list(seen.values())

        # Create batch events from collected events
        for batch_cls in BATCH_EVENT_REGISTRY:
            # Find events that should be collected by this batch type
            collected = [e for e in events_to_publish if type(e) in batch_cls.collect_events]

            # Find model mutations relevant to this batch type
            changed_models = [m for m in batch_cls.trigger_models if m in self._mutated_models]

            # Create batch event if there are collected events OR model mutations
            if collected or changed_models:
                batch_event = batch_cls.from_collected(collected, changed_models=changed_models)
                if batch_event is not None:
                    events_to_publish.append(batch_event)

        # Publish all events
        coros = [self._mercure_service.publish(e) for e in events_to_publish]

        if self._bg_tasks:
            # Non-blocking: schedule via BackgroundTasks
            for coro in coros:
                self._bg_tasks.run(coro)
        else:
            # Blocking: await all directly
            await asyncio.gather(*coros, return_exceptions=True)

        # Clear state for next transaction
        self._pending_events.clear()
        self._mutated_models.clear()
