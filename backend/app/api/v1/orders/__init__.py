"""Orders API package.

This package contains all order-related API endpoints organized by domain:
- order_routes: Order CRUD operations (list, get, sync, fetch from Shopify)
- image_routes: Image queries and version selection
- coloring_routes: Coloring generation and retry
- svg_routes: SVG generation and retry
"""

from fastapi import APIRouter

from app.api.v1.orders.coloring_routes import router as coloring_router
from app.api.v1.orders.image_routes import router as image_router
from app.api.v1.orders.order_routes import router as order_router
from app.api.v1.orders.svg_routes import router as svg_router

# Create a combined router for all order-related endpoints
router = APIRouter()

# Include all sub-routers
router.include_router(order_router)
router.include_router(image_router)
router.include_router(coloring_router)
router.include_router(svg_router)

__all__ = ["router"]
