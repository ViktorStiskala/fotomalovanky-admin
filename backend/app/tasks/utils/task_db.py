"""Database session utilities for Dramatiq background tasks."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.db.tracked_session import TrackedAsyncSession
from app.services.mercure.publish_service import MercurePublishService
from app.tasks.utils.background_tasks import BackgroundTasks


@asynccontextmanager
async def task_db_session(
    bg_tasks: BackgroundTasks | None = None,
    mercure_service: MercurePublishService | None = None,
) -> AsyncGenerator[TrackedAsyncSession]:
    """Context manager that provides a database session for background tasks.

    Creates a fresh engine bound to the current event loop, yields a session,
    and ensures proper cleanup of both the session and engine connection pool.

    This is necessary because each asyncio.run() call creates a new event loop,
    and the database connections must be bound to the current event loop.

    Args:
        bg_tasks: Optional BackgroundTasks instance for non-blocking Mercure publishes.
                  If provided, Mercure events are scheduled via bg_tasks.run().
                  If not provided, events are awaited directly via asyncio.gather().
        mercure_service: Optional MercurePublishService instance.
                         If not provided, a new instance is created.

    Usage:
        # With background tasks (non-blocking publishes)
        async with task_db_session(bg_tasks=bg_tasks) as session:
            # Use session for database operations
            # Mercure events are published in background after commit
            ...

        # Without background tasks (blocking publishes)
        async with task_db_session() as session:
            # Mercure events are awaited after commit
            ...
    """
    engine = create_async_engine(
        settings.database_url,
        echo=False,  # SQL logging controlled via structlog configuration
        future=True,
        pool_size=2,
        max_overflow=3,
        pool_pre_ping=True,
    )
    session_maker = async_sessionmaker(
        engine,
        class_=TrackedAsyncSession,
        expire_on_commit=False,
    )
    async with session_maker() as session:
        # Inject bg_tasks and mercure_service for auto-tracking
        session._bg_tasks = bg_tasks
        session._mercure_service = mercure_service or MercurePublishService()

        try:
            yield session
            await session.commit()
        except BaseException:
            await session.rollback()
            raise
    # Dispose engine to release all connections back to PostgreSQL
    await engine.dispose()
