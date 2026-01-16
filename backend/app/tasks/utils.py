"""Shared utilities for Dramatiq background tasks."""

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


@asynccontextmanager
async def task_db_session() -> AsyncGenerator[AsyncSession]:
    """Context manager that provides a database session for background tasks.

    Creates a fresh engine bound to the current event loop, yields a session,
    and ensures proper cleanup of both the session and engine connection pool.

    This is necessary because each asyncio.run() call creates a new event loop,
    and the database connections must be bound to the current event loop.

    Usage:
        async with task_db_session() as session:
            # Use session for database operations
            ...
    """
    engine = create_async_engine(
        settings.database_url,
        echo=settings.debug,
        future=True,
        pool_size=2,
        max_overflow=3,
        pool_pre_ping=True,
    )
    session_maker = async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )
    async with session_maker() as session:
        try:
            yield session
        finally:
            pass  # Session cleanup handled by context manager
    # Dispose engine to release all connections back to PostgreSQL
    await engine.dispose()
