"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import events, health, orders, webhooks
from app.config import settings
from app.db import dispose_engine
from app.logging import setup_logging
from app.services.storage.storage_service import S3StorageService

# Configure logging before anything else
setup_logging()

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    logger.info("Starting Fotomalovanky Admin API", debug=settings.debug)

    # Ensure S3 bucket exists
    storage = S3StorageService()
    await storage.ensure_bucket_exists()
    logger.info("S3 storage initialized", bucket=settings.s3_bucket)

    yield

    # Shutdown
    logger.info("Shutting down Fotomalovanky Admin API")
    await dispose_engine()
    logger.info("Database connections disposed")


app = FastAPI(
    title="Fotomalovanky Admin API",
    description="Order processing API for Fotomalovanky.cz",
    version="0.1.0",
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.backend_cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# API routes
app.include_router(health.router, prefix="/api/v1", tags=["health"])
app.include_router(orders.router, prefix="/api/v1", tags=["orders"])
app.include_router(webhooks.router, prefix="/api/v1", tags=["webhooks"])
app.include_router(events.router, prefix="/api/v1", tags=["events"])
