"""FastAPI dependencies for service injection."""

from typing import Annotated

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_session
from app.services.coloring.coloring_service import ColoringService
from app.services.coloring.vectorizer_service import VectorizerService
from app.services.external.mercure import MercureService
from app.services.orders.image_service import OrderImageService
from app.services.orders.order_service import OrderService
from app.services.storage.storage_service import LocalStorageService, StorageService


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


def get_storage_service() -> StorageService:
    """Get a StorageService instance."""
    return LocalStorageService()


def get_mercure_service() -> MercureService:
    """Get a MercureService instance."""
    return MercureService()


# Type aliases for cleaner endpoint signatures
OrderServiceDep = Annotated[OrderService, Depends(get_order_service)]
ImageServiceDep = Annotated[OrderImageService, Depends(get_image_service)]
ColoringServiceDep = Annotated[ColoringService, Depends(get_coloring_service)]
VectorizerServiceDep = Annotated[VectorizerService, Depends(get_vectorizer_service)]
StorageServiceDep = Annotated[StorageService, Depends(get_storage_service)]
MercureServiceDep = Annotated[MercureService, Depends(get_mercure_service)]
