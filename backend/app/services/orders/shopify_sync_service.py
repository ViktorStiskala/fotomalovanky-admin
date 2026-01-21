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

from app.db.mercure_protocol import mercure_autotrack
from app.db.tracked_session import TrackedAsyncSession
from app.models.enums import OrderStatus
from app.models.order import LINE_ITEM_POSITION_CONSTRAINT, Image, LineItem, Order
from app.models.utils.auto_increment import AutoIncrementOnConflict
from app.services.external.shopify import ShopifyService
from app.services.mercure.events import OrderUpdateEvent

if TYPE_CHECKING:
    from app.services.external.shopify_client.graphql_client.get_order_details import (
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
    failed: int
    total: int

    @property
    def has_changes(self) -> bool:
        """Check if any orders were imported or updated."""
        return self.imported > 0 or self.updated > 0


@mercure_autotrack(OrderUpdateEvent)
class ShopifySyncService:
    """Service for synchronizing orders from Shopify.

    This service handles the business logic of fetching and creating
    line items and images from Shopify data. Task dispatch and Mercure
    notifications are handled by the task layer.
    """

    session: TrackedAsyncSession  # Required by MercureTrackable protocol

    def __init__(self, session: TrackedAsyncSession):
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
        2. Create LineItem records
        3. Create Image records

        Note: Order metadata (payment status, shipping method) is updated by
        OrderService.create_or_update_from_shopify() before this method is called.

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

        # Process all line items
        has_images_to_download = False
        for edge in shopify_order.line_items.edges:
            if await self._process_line_item(edge.node, order.id):
                has_images_to_download = True

        await self.session.commit()

        return SyncResult(success=True, has_images_to_download=has_images_to_download)

    async def sync_orders_batch(self, limit: int = 20) -> tuple[BatchSyncResult, list[str]]:
        """Fetch recent orders from Shopify and sync them directly.

        This method:
        1. Fetches order list from Shopify
        2. Creates/updates Order records via OrderService
        3. Calls sync_single_order directly for each order needing sync
        4. Returns list of order IDs that need image downloads

        Args:
            limit: Maximum number of orders to fetch

        Returns:
            Tuple of (BatchSyncResult, list of order IDs needing image download)
        """
        from app.services.orders.order_service import OrderService

        # Fetch from Shopify API
        shopify_orders = await self.shopify.list_recent_orders(limit=limit)
        if not shopify_orders:
            raise RuntimeError("Failed to fetch orders from Shopify")

        imported = 0
        updated = 0
        skipped = 0
        failed = 0
        orders_needing_download: list[str] = []

        order_service = OrderService(self.session)

        for edge in shopify_orders.edges:
            shopify_order = edge.node
            shopify_id = int(shopify_order.legacy_resource_id)

            try:
                order, action = await order_service.create_or_update_from_shopify(shopify_order)

                if action == "imported":
                    imported += 1
                elif action == "updated":
                    updated += 1
                else:
                    skipped += 1
                    continue  # Skip already-processed orders

                # Set Mercure context for this order (required by @mercure_autotrack)
                self.session.set_mercure_context(Order.id == order.id)  # type: ignore[arg-type]

                # Set status to PROCESSING before sync
                order.status = OrderStatus.PROCESSING
                await self.session.commit()

                # Call sync_single_order directly
                sync_result = await self.sync_single_order(order)

                if not sync_result.success:
                    order.status = OrderStatus.ERROR
                    await self.session.commit()
                    logger.error(
                        "Order sync failed",
                        order_id=order.id,
                        shopify_id=shopify_id,
                        error=sync_result.error,
                    )
                elif sync_result.has_images_to_download:
                    # Status remains PROCESSING, download task will update
                    orders_needing_download.append(order.id)
                else:
                    order.status = OrderStatus.READY_FOR_REVIEW
                    await self.session.commit()

            except Exception as e:
                logger.error(
                    "Failed to sync order",
                    shopify_id=shopify_id,
                    error=str(e),
                )
                failed += 1
                continue

        logger.info(
            "Completed Shopify order fetch",
            imported=imported,
            updated=updated,
            skipped=skipped,
            failed=failed,
            total=len(shopify_orders.edges),
        )

        result = BatchSyncResult(
            imported=imported,
            updated=updated,
            skipped=skipped,
            failed=failed,
            total=len(shopify_orders.edges),
        )
        return result, orders_needing_download

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

