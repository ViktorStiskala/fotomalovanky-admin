"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1 import health, orders, webhooks
from app.config import settings
from app.db import dispose_engine

logger = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Application lifespan handler for startup/shutdown events."""
    # Startup
    logger.info("Starting Fotomalovanky Admin API", debug=settings.debug)
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
