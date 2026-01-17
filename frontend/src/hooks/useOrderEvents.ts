import { useCallback } from "react";
import { queryClient } from "@/lib/queryClient";
import { useMercure } from "./useMercure";
import {
  getGetOrderQueryKey,
  getListOrdersQueryKey,
  getOrderImage,
} from "@/api/generated/orders/orders";
import type {
  ImageStatusEvent,
  ImageUpdateEvent,
  ListUpdateEvent,
  OrderDetailResponse,
  OrderUpdateEvent,
} from "@/api/generated/schemas";

// Union type for all Mercure events
type MercureEvent = ImageStatusEvent | ImageUpdateEvent | ListUpdateEvent | OrderUpdateEvent;

/**
 * Custom hook that subscribes to Mercure SSE events for a specific order.
 *
 * Handles three types of events:
 * - `order_update`: Full refetch of order data (structural changes like COMPLETED, ERROR, new version)
 * - `image_status`: Efficient single image update (status-only changes during processing)
 * - `image_update`: Efficient single image update (selection changes, metadata updates)
 *
 * This enables real-time status updates as background workers process the order,
 * with minimal network overhead during frequent status changes.
 *
 * @param shopifyId - The Shopify order ID (numeric)
 */
export function useOrderEvents(shopifyId: number): void {
  const handleMessage = useCallback(
    async (data: unknown) => {
      const event = data as MercureEvent;
      console.log(`[Mercure] Order ${shopifyId} event received:`, event);

      if (event.type === "image_status" || event.type === "image_update") {
        // Efficient update: fetch only the updated image
        try {
          const response = await getOrderImage(shopifyId, event.image_id);

          // Handle the response (may have status/data structure from Orval)
          const imageData = "data" in response ? response.data : response;

          // Update the cache by replacing just this image in the order data
          queryClient.setQueryData(
            getGetOrderQueryKey(shopifyId),
            (oldData: { data: OrderDetailResponse } | OrderDetailResponse | undefined) => {
              if (!oldData) return oldData;

              // Handle both wrapped and unwrapped response types
              const orderData = "data" in oldData ? oldData.data : oldData;

              const updatedOrderData = {
                ...orderData,
                line_items: orderData.line_items.map((li) => ({
                  ...li,
                  images: li.images.map((img) => (img.id === event.image_id ? imageData : img)),
                })),
              };

              // Return in the same shape as the input
              return "data" in oldData ? { ...oldData, data: updatedOrderData } : updatedOrderData;
            }
          );
        } catch (error) {
          console.error("[Mercure] Failed to fetch image:", error);
          // Fallback: invalidate the whole order query
          queryClient.invalidateQueries({ queryKey: getGetOrderQueryKey(shopifyId) });
        }
      } else {
        // For order_update events or list_update: invalidate to trigger full refetch
        queryClient.invalidateQueries({ queryKey: getGetOrderQueryKey(shopifyId) });

        // Also invalidate the orders list in case status changed
        queryClient.invalidateQueries({ queryKey: getListOrdersQueryKey() });
      }
    },
    [shopifyId]
  );

  useMercure(`orders/${shopifyId}`, handleMessage, shopifyId > 0);
}
