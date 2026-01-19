"""Background task utilities for async fire-and-forget operations."""

import asyncio
from collections import defaultdict
from collections.abc import Awaitable, Callable
from functools import wraps
from typing import Any, ParamSpec, TypeVar

import structlog

logger = structlog.get_logger(__name__)

T = TypeVar("T")
P = ParamSpec("P")


class BackgroundTasks:
    """Collects background asyncio tasks that should finish before the function returns.

    Usage:
        bg = BackgroundTasks()
        bg.run(some_coroutine())
        bg.run(another_coroutine())
        await bg.wait(timeout=30)  # Wait for all tasks with timeout

    Typically used via the @background_tasks decorator which handles wait() automatically.
    """

    def __init__(self) -> None:
        self._tasks: list[asyncio.Task[Any]] = []
        self._counters: dict[str, int] = defaultdict(int)

    def _task_key(self, coro: Awaitable[Any]) -> str:
        """Generate a human-readable key for the task."""
        # Prefer __qualname__ for methods
        name = getattr(coro, "__qualname__", None)
        if name:
            return str(name)

        # Fall back to code object name for coroutines
        code = getattr(coro, "cr_code", None)
        if code:
            return str(code.co_name)

        return "task"

    def run(self, coro: Awaitable[Any]) -> None:
        """Schedule a coroutine as a background task.

        The task will be awaited when wait() is called.
        """
        key = self._task_key(coro)
        self._counters[key] += 1
        name = f"bg:{key}:{self._counters[key]}"

        task: asyncio.Task[Any] = asyncio.create_task(coro, name=name)  # type: ignore[arg-type]
        self._tasks.append(task)

    async def wait(self, *, timeout: float) -> None:
        """Wait for all background tasks to complete with timeout.

        If timeout is exceeded, remaining tasks are cancelled.
        Exceptions from tasks are logged but not raised.
        """
        if not self._tasks:
            return

        try:
            results = await asyncio.wait_for(
                asyncio.gather(*self._tasks, return_exceptions=True),
                timeout=timeout,
            )
            # Log any exceptions
            for task, result in zip(self._tasks, results, strict=True):
                if isinstance(result, Exception):
                    logger.warning(
                        "Background task failed",
                        task_name=task.get_name(),
                        error=str(result),
                    )
        except asyncio.TimeoutError:
            logger.warning(
                "Background tasks timed out, cancelling",
                timeout=timeout,
                pending=sum(1 for t in self._tasks if not t.done()),
            )
            # Cancel remaining tasks
            for task in self._tasks:
                if not task.done():
                    task.cancel()
            # Wait for cancellation to complete
            await asyncio.gather(*self._tasks, return_exceptions=True)


def background_tasks(
    *, timeout: float = 30.0
) -> Callable[[Callable[P, Awaitable[T]]], Callable[P, Awaitable[T]]]:
    """Decorator that injects BackgroundTasks and waits for them on return.

    The decorated function must accept a keyword-only `bg_tasks: BackgroundTasks` parameter.
    After the function returns (or raises), all scheduled background tasks are awaited
    with the specified timeout.

    Usage:
        @background_tasks(timeout=30)
        async def my_func(..., *, bg_tasks: BackgroundTasks) -> None:
            bg_tasks.run(some_async_operation())
            # ... main logic ...
            # Background tasks are awaited after return
    """

    def decorator(fn: Callable[P, Awaitable[T]]) -> Callable[P, Awaitable[T]]:
        @wraps(fn)
        async def wrapper(*args: P.args, **kwargs: P.kwargs) -> T:
            bg = BackgroundTasks()
            try:
                return await fn(*args, bg_tasks=bg, **kwargs)  # type: ignore[arg-type]
            finally:
                await bg.wait(timeout=timeout)

        return wrapper

    return decorator
