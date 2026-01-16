"""Database engine and session configuration."""

from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.models.coloring  # noqa: F401

# Register all models with SQLAlchemy (required for relationship resolution)
# Import order matters: order.py defines Image, coloring.py references it
import app.models.order  # noqa: F401
from app.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,
    future=True,
    pool_size=5,
    max_overflow=10,
    pool_pre_ping=True,  # Verify connections before use
    pool_recycle=300,  # Recycle connections after 5 minutes
)

async_session_maker = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Dependency that provides an async database session."""
    async with async_session_maker() as session:
        yield session


async def dispose_engine() -> None:
    """Dispose of the engine and release all connections.

    Should be called during application shutdown.
    """
    await engine.dispose()
