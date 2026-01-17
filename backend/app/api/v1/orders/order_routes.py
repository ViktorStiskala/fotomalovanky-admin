"""Order CRUD API endpoints."""

import structlog
from fastapi import APIRouter, HTTPException

from app.api.v1.orders.dependencies import OrderServiceDep
from app.api.v1.orders.schemas import (
    OrderDetailResponse,
    OrderListResponse,
    OrderResponse,
    StatusResponse,
)
from app.services.orders.exceptions import OrderNotFound
from app.tasks.orders.fetch_shopify import fetch_orders_from_shopify
from app.tasks.orders.order_ingestion import ingest_order

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["orders"])


@router.get("/orders", response_model=OrderListResponse, operation_id="listOrders")
async def list_orders(
    service: OrderServiceDep,
    skip: int = 0,
    limit: int = 50,
) -> OrderListResponse:
    """List all orders with pagination."""
    orders, total = await service.list_orders(skip=skip, limit=limit)

    return OrderListResponse(
        orders=[OrderResponse.from_model(order) for order in orders],
        total=total,
    )


@router.get("/orders/{shopify_id}", response_model=OrderDetailResponse, operation_id="getOrder")
async def get_order(
    shopify_id: int,
    service: OrderServiceDep,
) -> OrderDetailResponse:
    """Get a single order with line items and images by Shopify order ID."""
    try:
        order = await service.get_order(shopify_id)
        return OrderDetailResponse.from_model(order)
    except OrderNotFound:
        raise HTTPException(status_code=404, detail="Order not found")


@router.post("/orders/{shopify_id}/sync", response_model=StatusResponse, operation_id="syncOrder")
async def sync_order(
    shopify_id: int,
    service: OrderServiceDep,
) -> StatusResponse:
    """Manually trigger a sync/re-processing of an order."""
    try:
        order = await service.prepare_sync(shopify_id)

        # Dispatch task after DB commit
        assert order.id is not None
        ingest_order.send(order.id)

        return StatusResponse(
            status="queued",
            message=f"Order {order.shopify_order_number} queued for sync",
        )
    except OrderNotFound:
        raise HTTPException(status_code=404, detail="Order not found")


@router.post("/orders/fetch-from-shopify", response_model=StatusResponse, operation_id="fetchFromShopify")
async def fetch_from_shopify_endpoint(
    limit: int = 20,
) -> StatusResponse:
    """
    Queue a background task to fetch recent orders from Shopify.

    - New orders are created and queued for processing
    - Existing orders with missing images or in error state are re-queued
    - Orders that are fully processed are skipped
    - Progress is pushed via Mercure updates
    """
    # Dispatch the background task
    fetch_orders_from_shopify.send(limit)

    return StatusResponse(
        status="queued",
        message="Shopify order fetch queued",
    )
