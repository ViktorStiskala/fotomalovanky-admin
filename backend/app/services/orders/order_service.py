"""Order management service.

This service handles business logic for order management.
Tasks should be dispatched by API routes, not by this service.
External API calls (Shopify) should be in Dramatiq tasks, not in this service.
"""

from datetime import UTC
from typing import TYPE_CHECKING

import structlog
from dateutil.parser import parse as parse_datetime
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload
from sqlmodel import select

from app.models.coloring import ColoringVersion
from app.models.enums import OrderStatus
from app.models.order import Image, LineItem, Order
from app.services.orders.exceptions import OrderNotFound
from app.utils.shopify_helpers import build_customer_name, normalize_order_number

if TYPE_CHECKING:
    from app.services.external.shopify_client.graphql_client.list_recent_orders import (
        ListRecentOrdersOrdersEdgesNode,
    )

logger = structlog.get_logger(__name__)


class OrderService:
    """Service for order management operations.

    Note: This service does NOT dispatch Dramatiq tasks or call external APIs.
    API routes should call service methods and dispatch tasks separately.
    External API calls should be made in Dramatiq tasks.
    """

    def __init__(self, session: AsyncSession):
        self.session = session

    async def list_orders(self, *, skip: int = 0, limit: int = 50) -> tuple[list[Order], int]:
        """List orders with pagination. Returns (orders, total_count)."""
        # Get orders with eager loading of line_items
        orders_statement = (
            select(Order)
            .options(selectinload(Order.line_items))  # type: ignore[arg-type]
            .offset(skip)
            .limit(limit)
            .order_by(Order.created_at.desc())  # type: ignore[attr-defined]
        )
        orders_result = await self.session.execute(orders_statement)
        orders = list(orders_result.scalars().all())

        # Get total count (efficient - uses SQL COUNT)
        count_statement = select(func.count()).select_from(Order)
        count_result = await self.session.execute(count_statement)
        total = count_result.scalar() or 0

        return orders, total

    async def get_order(self, order_number: str) -> Order:
        """Get order by number with full eager loading."""
        normalized = normalize_order_number(order_number)
        statement = (
            select(Order)
            .options(
                selectinload(Order.line_items)  # type: ignore[arg-type]
                .selectinload(LineItem.images)  # type: ignore[arg-type]
                .selectinload(Image.coloring_versions)  # type: ignore[arg-type]
                .selectinload(ColoringVersion.svg_versions)  # type: ignore[arg-type]
            )
            .where(Order.shopify_order_number == normalized)
        )
        result = await self.session.execute(statement)
        order = result.scalars().first()
        if not order:
            raise OrderNotFound()
        return order

    async def get_order_basic(self, order_number: str) -> Order:
        """Get order by number without eager loading (for simple checks)."""
        normalized = normalize_order_number(order_number)
        statement = select(Order).where(Order.shopify_order_number == normalized)
        result = await self.session.execute(statement)
        order = result.scalars().first()
        if not order:
            raise OrderNotFound()
        return order

    async def prepare_sync(self, order_number: str) -> Order:
        """Reset order status for re-processing.

        Returns the updated order. Caller is responsible for dispatching the task.
        """
        normalized = normalize_order_number(order_number)
        statement = select(Order).where(Order.shopify_order_number == normalized)
        result = await self.session.execute(statement)
        order = result.scalars().first()
        if not order:
            raise OrderNotFound()

        order.status = OrderStatus.PENDING
        await self.session.commit()

        return order

    async def create_or_update_from_shopify(
        self,
        shopify_order: "ListRecentOrdersOrdersEdgesNode",
    ) -> tuple[Order, str]:
        """Create or update an order from Shopify data.

        Returns (order, action) where action is 'imported', 'updated', or 'skipped'.
        Caller is responsible for dispatching ingest tasks when action != 'skipped'.
        """
        shopify_id = int(shopify_order.legacy_resource_id)

        # Check if order already exists
        existing_result = await self.session.execute(
            select(Order)
            .options(selectinload(Order.line_items).selectinload(LineItem.images))  # type: ignore[arg-type]
            .where(Order.shopify_id == shopify_id)
        )
        existing_order = existing_result.scalars().first()

        if existing_order:
            # Always update basic order info from Shopify
            self._update_order_from_shopify(existing_order, shopify_order)

            if self._order_needs_reprocessing(existing_order):
                existing_order.status = OrderStatus.PENDING
                await self.session.commit()
                return existing_order, "updated"
            else:
                await self.session.commit()
                logger.debug("Order already processed, skipping", shopify_id=shopify_id)
                return existing_order, "skipped"

        # Build customer name from customer object
        customer_name = None
        if shopify_order.customer:
            customer_name = build_customer_name(
                shopify_order.customer.first_name,
                shopify_order.customer.last_name,
            )

        # Extract payment status (convert enum to string if present)
        payment_status = None
        if shopify_order.display_financial_status:
            payment_status = shopify_order.display_financial_status.value

        # Extract shipping method
        shipping_method = shopify_order.shipping_line.title if shopify_order.shipping_line else None

        # Parse Shopify created_at timestamp and convert to UTC for storage
        shopify_created_at = parse_datetime(str(shopify_order.created_at))
        if shopify_created_at.tzinfo is not None:
            shopify_created_at = shopify_created_at.astimezone(UTC)

        # Create new order
        order = Order(
            shopify_id=shopify_id,
            shopify_order_number=shopify_order.name,
            customer_email=shopify_order.email,
            customer_name=customer_name,
            payment_status=payment_status,
            shipping_method=shipping_method,
            status=OrderStatus.PENDING,
            created_at=shopify_created_at,
        )
        self.session.add(order)
        await self.session.commit()

        logger.info(
            "Imported order from Shopify",
            order_id=order.id,
            shopify_id=shopify_id,
            shopify_name=shopify_order.name,
        )

        return order, "imported"

    def _update_order_from_shopify(
        self,
        order: Order,
        shopify_order: "ListRecentOrdersOrdersEdgesNode",
    ) -> None:
        """Update order with latest data from Shopify."""
        if shopify_order.display_financial_status:
            order.payment_status = shopify_order.display_financial_status.value

        if shopify_order.shipping_line:
            order.shipping_method = shopify_order.shipping_line.title

        if shopify_order.customer:
            customer_name = build_customer_name(
                shopify_order.customer.first_name,
                shopify_order.customer.last_name,
            )
            if customer_name:
                order.customer_name = customer_name

        if shopify_order.email:
            order.customer_email = shopify_order.email

    def _order_needs_reprocessing(self, order: Order) -> bool:
        """Check if an existing order needs re-processing."""
        if order.status == OrderStatus.ERROR:
            logger.info("Order in error state, re-queuing", order_id=order.id)
            return True

        if len(order.line_items) == 0:
            logger.info("Order has no line items, re-queuing", order_id=order.id)
            return True

        for li in order.line_items:
            for img in li.images:
                if not img.local_path:
                    logger.info("Order has undownloaded images, re-queuing", order_id=order.id, image_id=img.id)
                    return True

        return False
