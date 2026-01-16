"""Task decorators for Dramatiq actors."""

from collections.abc import Callable
from typing import Any

# Registry of tasks with recovery functions
_recoverable_tasks: list[tuple[Any, Callable[..., Any]]] = []


def task_recover(get_incomplete_fn: Callable[..., Any]) -> Callable[[Any], Any]:
    """Decorator to register a task for automatic recovery.

    The recovery function should be a classmethod on a service that takes
    an AsyncSession and returns a list of version IDs that need recovery.

    Usage:
        @task_recover(ColoringService.get_incomplete_versions)
        @dramatiq.actor(...)
        def generate_coloring(version_id: int) -> None: ...
    """

    def decorator(fn: Any) -> Any:
        fn._recovery_fn = get_incomplete_fn
        _recoverable_tasks.append((fn, get_incomplete_fn))
        return fn

    return decorator


def get_recoverable_tasks() -> list[tuple[Any, Callable[..., Any]]]:
    """Return all registered recoverable tasks."""
    return _recoverable_tasks
