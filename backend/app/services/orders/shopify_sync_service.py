"""Shopify order synchronization service.

This service handles syncing orders from Shopify:
- Fetching order details and creating line items/images
- Batch fetching recent orders

Tasks dispatch is handled by the task layer, not this service.
"""

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import select

from app.models.enums import OrderStatus
from app.models.order import LINE_ITEM_POSITION_CONSTRAINT, Image, LineItem, Order
from app.models.utils.auto_increment import AutoIncrementOnConflict
from app.services.external.shopify import ShopifyService

if TYPE_CHECKING:
    from app.services.external.shopify_client.graphql_client.get_order_details import (
        GetOrderDetailsOrder,
        GetOrderDetailsOrderLineItemsEdgesNode,
    )

logger = structlog.get_logger(__name__)


def extract_numeric_id(gid: str) -> int:
    """Extract numeric ID from Shopify GID format (e.g., 'gid://shopify/LineItem/12345')."""
    match = re.search(r"/(\d+)$", gid)
    if match:
        return int(match.group(1))
    raise ValueError(f"Could not extract numeric ID from GID: {gid}")


def extract_image_urls(attrs: dict[str, str]) -> list[tuple[int, str]]:
    """Extract image URLs and positions from custom attributes.

    Looks for keys like 'Fotka 1', 'Fotka 2', or 'Fotka (4)-1', 'Fotka (4)-2', etc.

    Returns:
        List of (position, url) tuples
    """
    images = []
    for key, value in attrs.items():
        if not value or not value.startswith("http"):
            continue

        # Match patterns like "Fotka 1", "Fotka (4)-1", "Fotka (4)-2"
        match = re.match(r"Fotka\s*(?:\(\d+\))?-?(\d+)", key)
        if match:
            position = int(match.group(1))
            images.append((position, value))

    return sorted(images, key=lambda x: x[0])


@dataclass
class SyncResult:
    """Result of syncing a single order."""

    success: bool
    has_images_to_download: bool
    error: str | None = None


@dataclass
class BatchSyncResult:
    """Result of batch syncing orders from Shopify."""

    imported: int
    updated: int
    skipped: int
    total: int

    @property
    def has_changes(self) -> bool:
        """Check if any orders were imported or updated."""
        return self.imported > 0 or self.updated > 0


class ShopifySyncService:
    """Service for synchronizing orders from Shopify.

    This service handles the business logic of fetching and creating
    line items and images from Shopify data. Task dispatch and Mercure
    notifications are handled by the task layer.
    """

    def __init__(self, session: AsyncSession):
        """Initialize sync service.

        Args:
            session: Database session for creating records
        """
        self.session = session
        self.shopify = ShopifyService()

    async def sync_single_order(self, order: Order) -> SyncResult:
        """Fetch order details from Shopify and create line items/images.

        This method handles the core ingestion logic:
        1. Fetch order details from Shopify GraphQL API
        2. Update order metadata (payment status, shipping method)
        3. Create LineItem records
        4. Create Image records

        Args:
            order: Order to sync (must have shopify_id)

        Returns:
            SyncResult with success status and whether images need downloading
        """
        assert order.id is not None, "Order ID cannot be None"

        if order.shopify_id is None:
            logger.error("Order has no shopify_id, cannot sync", order_id=order.id)
            return SyncResult(success=False, has_images_to_download=False, error="Order has no Shopify ID")

        shopify_order = await self.shopify.get_order_details(order.shopify_id)
        if not shopify_order:
            logger.error("Failed to fetch order from Shopify", order_id=order.id)
            return SyncResult(success=False, has_images_to_download=False, error="Failed to fetch from Shopify")

        logger.info(
            "Fetched Shopify order",
            order_id=order.id,
            shopify_name=shopify_order.name,
            fulfillment_status=shopify_order.display_fulfillment_status.value,
            line_item_count=len(shopify_order.line_items.edges),
        )

        # Update order metadata from Shopify
        self._update_order_metadata(order, shopify_order)

        # Process all line items
        has_images_to_download = False
        for edge in shopify_order.line_items.edges:
            if await self._process_line_item(edge.node, order.id):
                has_images_to_download = True

        await self.session.commit()

        return SyncResult(success=True, has_images_to_download=has_images_to_download)

    async def sync_orders_batch(self, limit: int = 20) -> tuple[BatchSyncResult, list[tuple[Order, str]]]:
        """Fetch recent orders from Shopify and sync them.

        This method uses OrderService.create_or_update_from_shopify internally
        for consistency with the existing order creation logic.

        Args:
            limit: Maximum number of orders to fetch

        Returns:
            Tuple of (BatchSyncResult, list of (order, action) tuples for orders needing ingestion)
        """
        from app.services.orders.order_service import OrderService

        # Fetch from Shopify API
        shopify_orders = await self.shopify.list_recent_orders(limit=limit)
        if not shopify_orders:
            raise RuntimeError("Failed to fetch orders from Shopify")

        imported = 0
        updated = 0
        skipped = 0
        orders_to_ingest: list[tuple[Order, str]] = []

        order_service = OrderService(self.session)

        for edge in shopify_orders.edges:
            shopify_order = edge.node
            order, action = await order_service.create_or_update_from_shopify(shopify_order)

            if action == "imported":
                imported += 1
                orders_to_ingest.append((order, action))
            elif action == "updated":
                updated += 1
                orders_to_ingest.append((order, action))
            else:
                skipped += 1

        logger.info(
            "Completed Shopify order fetch",
            imported=imported,
            updated=updated,
            skipped=skipped,
            total=len(shopify_orders.edges),
        )

        result = BatchSyncResult(
            imported=imported,
            updated=updated,
            skipped=skipped,
            total=len(shopify_orders.edges),
        )
        return result, orders_to_ingest

    def _update_order_metadata(self, order: Order, shopify_order: "GetOrderDetailsOrder") -> None:
        """Update order with metadata from Shopify."""
        if shopify_order.display_financial_status:
            order.payment_status = shopify_order.display_financial_status.value
        if shopify_order.shipping_line:
            order.shipping_method = shopify_order.shipping_line.title

    async def _process_line_item(
        self,
        shopify_line_item: "GetOrderDetailsOrderLineItemsEdgesNode",
        order_id: str,
    ) -> bool:
        """Process a single line item and its images.

        Returns:
            True if there are images that need downloading, False otherwise
        """
        shopify_line_item_id = extract_numeric_id(shopify_line_item.id)
        attrs = ShopifyService.parse_custom_attributes(shopify_line_item.custom_attributes)

        logger.debug(
            "Processing line item",
            title=shopify_line_item.title,
            shopify_line_item_id=shopify_line_item_id,
            quantity=shopify_line_item.quantity,
            custom_attrs=attrs,
        )

        # Check if LineItem already exists (idempotency)
        existing_stmt = select(LineItem).where(LineItem.shopify_line_item_id == shopify_line_item_id)
        existing_result = await self.session.execute(existing_stmt)
        line_item = existing_result.scalars().first()

        if not line_item:
            # Use AutoIncrementOnConflict for position
            new_line_item: LineItem | None = None
            async for attempt in AutoIncrementOnConflict(
                session=self.session,
                model_class=LineItem,
                increment_column=LineItem.position,
                filter_columns={LineItem.order_id: order_id},
                constraint=LINE_ITEM_POSITION_CONSTRAINT,
            ):
                async with attempt:
                    new_line_item = LineItem(
                        order_id=order_id,
                        position=attempt.value,
                        shopify_line_item_id=shopify_line_item_id,
                        title=shopify_line_item.title,
                        quantity=shopify_line_item.quantity,
                        dedication=attrs.get("Věnování"),
                        layout=attrs.get("Rozvržení"),
                    )
                    self.session.add(new_line_item)
                    await self.session.flush()
            # AutoIncrementOnConflict guarantees success or raises
            assert new_line_item is not None
            line_item = new_line_item
            logger.info("Created line item", line_item_id=line_item.id, shopify_line_item_id=shopify_line_item_id)

        assert line_item.id is not None, "LineItem ID cannot be None after flush"
        return await self._create_images_for_line_item(line_item.id, attrs)

    async def _create_images_for_line_item(
        self,
        line_item_id: int,
        attrs: dict[str, str],
    ) -> bool:
        """Create image records for a line item.

        Returns:
            True if there are images that need downloading, False otherwise
        """
        has_images_to_download = False
        image_urls = extract_image_urls(attrs)

        for position, url in image_urls:
            img_stmt = select(Image).where(Image.line_item_id == line_item_id, Image.position == position)
            img_result = await self.session.execute(img_stmt)
            image = img_result.scalars().first()

            if not image:
                image = Image(line_item_id=line_item_id, position=position, original_url=url)
                self.session.add(image)
                await self.session.flush()
                has_images_to_download = True
                logger.info("Created image record", image_id=image.id, position=position, url=url[:50] + "...")
            elif not image.file_ref:
                has_images_to_download = True

        return has_images_to_download

    @staticmethod
    async def get_incomplete_ingestions(session: AsyncSession) -> list[str]:
        """Get order IDs with incomplete ingestion.

        This is used by the task recovery decorator to find orders
        that need their ingestion completed.

        Args:
            session: Database session

        Returns:
            List of order IDs (ULIDs) in PROCESSING state
        """
        statement = select(Order.id).where(Order.status == OrderStatus.PROCESSING)
        result = await session.execute(statement)
        return list(result.scalars().all())
