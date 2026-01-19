"""Mercure publishing contexts - capture common arguments for repeated publishes."""

from abc import ABC, abstractmethod
from collections.abc import Awaitable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from app.models.enums import VersionType

if TYPE_CHECKING:
    from app.services.mercure.publish_service import MercurePublishService
    from app.tasks.utils.background_tasks import BackgroundTasks


@dataclass
class MercureContext(ABC):
    """Base class for Mercure publishing contexts.

    Captures common arguments (service, order_id, etc.) so you only need
    to pass the changing value (e.g., status) on each publish.

    Supports two modes:
    - With bg_tasks: `mercure.publish(status)` schedules non-blocking
    - Without bg_tasks: `await mercure.publish_async(status)` awaits directly

    Subclasses implement `_build_coro()` to create the actual publish coroutine.
    """

    service: "MercurePublishService"
    bg_tasks: "BackgroundTasks | None" = field(default=None)

    @abstractmethod
    def _build_coro(self, *args: Any, **kwargs: Any) -> Awaitable[None]:
        """Build the coroutine to publish. Subclasses define the actual call."""
        ...

    def publish(self, *args: Any, **kwargs: Any) -> None:
        """Schedule publish as background task (non-blocking).

        Requires bg_tasks to be set in constructor.
        """
        if self.bg_tasks is None:
            raise RuntimeError(
                "Cannot use publish() without bg_tasks. " "Use publish_async() or pass bg_tasks to constructor."
            )
        self.bg_tasks.run(self._build_coro(*args, **kwargs))

    async def publish_async(self, *args: Any, **kwargs: Any) -> None:
        """Directly await the publish (blocking)."""
        await self._build_coro(*args, **kwargs)


@dataclass
class ImageStatusContext(MercureContext):
    """Context for publishing image status updates during processing.

    Usage (background):
        mercure = ImageStatusContext(
            service=mercure_service,
            bg_tasks=bg_tasks,
            order_id=order.id,
            image_id=image.id,
            version_id=version.id,
            status_type=VersionType.COLORING,
        )
        mercure.publish(ColoringProcessingStatus.PROCESSING)  # Non-blocking

    Usage (direct):
        mercure = ImageStatusContext(
            service=mercure_service,
            order_id=order.id,
            ...
        )
        await mercure.publish_async(ColoringProcessingStatus.PROCESSING)  # Blocking
    """

    order_id: str = ""
    image_id: int = 0
    version_id: int = 0
    status_type: VersionType = VersionType.COLORING

    def _build_coro(self, status: Any) -> Awaitable[None]:
        """Build coroutine for image status publish."""
        # VersionType values match the Literal type
        status_type_literal = "coloring" if self.status_type == VersionType.COLORING else "svg"
        return self.service.publish_image_status(
            order_id=self.order_id,
            image_id=self.image_id,
            status_type=status_type_literal,  # type: ignore[arg-type]
            version_id=self.version_id,
            status=status.value if hasattr(status, "value") else str(status),
        )


@dataclass
class OrderUpdateContext(MercureContext):
    """Context for publishing order updates.

    Usage:
        mercure = OrderUpdateContext(service=mercure_service, bg_tasks=bg_tasks, order_id=order.id)
        mercure.publish()  # No arguments needed
    """

    order_id: str = ""

    def _build_coro(self) -> Awaitable[None]:
        """Build coroutine for order update publish."""
        return self.service.publish_order_update(self.order_id)


@dataclass
class ListUpdateContext(MercureContext):
    """Context for publishing order list updates.

    Usage:
        mercure = ListUpdateContext(service=mercure_service, bg_tasks=bg_tasks)
        mercure.publish()
    """

    def _build_coro(self) -> Awaitable[None]:
        """Build coroutine for list update publish."""
        return self.service.publish_order_list_update()


@dataclass
class ImageUpdateContext(MercureContext):
    """Context for publishing image metadata updates (e.g., selection changes).

    Usage:
        mercure = ImageUpdateContext(
            service=mercure_service, bg_tasks=bg_tasks, order_id=order.id, image_id=image.id
        )
        mercure.publish()
    """

    order_id: str = ""
    image_id: int = 0

    def _build_coro(self) -> Awaitable[None]:
        """Build coroutine for image update publish."""
        return self.service.publish_image_update(
            order_id=self.order_id,
            image_id=self.image_id,
        )
