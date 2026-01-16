"""FastAPI dependencies for service injection."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.services.coloring.coloring_service import ColoringService
from app.services.coloring.vectorizer_service import VectorizerService
from app.services.orders.image_service import OrderImageService
from app.services.orders.order_service import OrderService


async def get_order_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderService:
    """Get an OrderService instance with the current session."""
    return OrderService(session)


async def get_image_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> OrderImageService:
    """Get an OrderImageService instance with the current session."""
    return OrderImageService(session)


async def get_coloring_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> ColoringService:
    """Get a ColoringService instance with the current session."""
    return ColoringService(session)


async def get_vectorizer_service(
    session: Annotated[AsyncSession, Depends(get_session)],
) -> VectorizerService:
    """Get a VectorizerService instance with the current session."""
    return VectorizerService(session)


# Type aliases for cleaner endpoint signatures
OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
ImageServiceDep = Annotated[OrderImageService, Depends(get_image_service)]
ColoringServiceDep = Annotated[ColoringService, Depends(get_coloring_service)]
VectorizerServiceDep = Annotated[VectorizerService, Depends(get_vectorizer_service)]
