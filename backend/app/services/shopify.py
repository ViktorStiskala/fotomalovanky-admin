"""Shopify GraphQL API client wrapper using ariadne-codegen."""

import structlog

from app.config import settings
from app.services.shopify_client.graphql_client import ShopifyClient
from app.services.shopify_client.graphql_client.get_order_details import (
    GetOrderDetailsOrder,
    GetOrderDetailsOrderLineItemsEdgesNodeCustomAttributes,
)
from app.services.shopify_client.graphql_client.list_recent_orders import (
    ListRecentOrdersOrders,
)

logger = structlog.get_logger(__name__)

# GraphQL endpoint URL
SHOPIFY_GRAPHQL_URL = f"{settings.shopify_store_url}/admin/api/2025-01/graphql.json"


def get_shopify_client() -> ShopifyClient:
    """Create a configured ShopifyClient instance."""
    if not settings.shopify_access_token or not settings.shopify_store_url:
        raise ValueError("Shopify credentials not configured")

    return ShopifyClient(
        url=SHOPIFY_GRAPHQL_URL,
        headers={"X-Shopify-Access-Token": settings.shopify_access_token},
    )


async def get_order_details(shopify_id: int) -> GetOrderDetailsOrder | None:
    """
    Fetch full order details from Shopify Admin GraphQL API.

    Args:
        shopify_id: Shopify order ID (numeric)

    Returns:
        Typed order data or None if not found
    """
    if not settings.shopify_access_token or not settings.shopify_store_url:
        logger.warning("Shopify credentials not configured")
        return None

    # Convert numeric ID to Shopify GID format
    gid = f"gid://shopify/Order/{shopify_id}"

    try:
        client = get_shopify_client()
        async with client:
            order = await client.get_order_details(id=gid)
            return order

    except Exception as e:
        logger.error("Failed to fetch order from Shopify", shopify_id=shopify_id, error=str(e))
        return None


async def list_recent_orders(limit: int = 20) -> ListRecentOrdersOrders | None:
    """
    Fetch recent orders from Shopify Admin GraphQL API.

    Args:
        limit: Maximum number of orders to fetch

    Returns:
        Typed orders list or None if failed
    """
    if not settings.shopify_access_token or not settings.shopify_store_url:
        logger.warning("Shopify credentials not configured")
        return None

    try:
        client = get_shopify_client()
        async with client:
            orders = await client.list_recent_orders(first=limit)
            return orders

    except Exception as e:
        logger.error("Failed to fetch recent orders from Shopify", limit=limit, error=str(e))
        return None


def parse_custom_attributes(
    attributes: list[GetOrderDetailsOrderLineItemsEdgesNodeCustomAttributes],
) -> dict[str, str]:
    """
    Parse Shopify custom attributes into a dict.

    Expected attributes:
    - "Fotka 1", "Fotka 2", etc. (image URLs)
    - "Věnování" (dedication text)
    - "Rozvržení" (layout type)
    """
    return {attr.key: attr.value for attr in attributes if attr.key and attr.value}
