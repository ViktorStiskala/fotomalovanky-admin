import { useCallback } from "react";
import { queryClient } from "@/lib/queryClient";
import { useMercure } from "./useMercure";
import {
  getGetOrderQueryKey,
  getListOrdersQueryKey,
  getOrderImage,
} from "@/api/generated/orders/orders";
import type {
  ImageUpdateEvent,
  OrderDetailResponse,
  OrderUpdateEvent,
} from "@/api/generated/schemas";

// Union type for events on the orders/{orderId} topic
// Note: ListUpdateEvent only goes to "orders" topic, not "orders/{orderId}"
type OrderEvent = ImageUpdateEvent | OrderUpdateEvent;

/**
 * Custom hook that subscribes to Mercure SSE events for a specific order.
 *
 * Handles two types of events:
 * - `order_update`: Full refetch of order data (structural changes like COMPLETED, ERROR, new version)
 * - `image_update`: Efficient single image update (status changes, selection changes, metadata updates)
 *
 * This enables real-time status updates as background workers process the order,
 * with minimal network overhead during frequent status changes.
 *
 * @param orderId - The Order ID (ULID string)
 */
export function useOrderEvents(orderId: string): void {
  const handleMessage = useCallback(
    async (data: unknown) => {
      const event = data as OrderEvent;
      console.log(`[Mercure] Order ${orderId} event received:`, event);

      if (event.type === "image_update") {
        // Efficient update: fetch only the updated image
        const imageEvent = event as ImageUpdateEvent;
        try {
          const response = await getOrderImage(orderId, imageEvent.image_id);

          // Handle the response (may have status/data structure from Orval)
          const imageData = "data" in response ? response.data : response;

          // Update the cache by replacing just this image in the order data
          queryClient.setQueryData(
            getGetOrderQueryKey(orderId),
            (oldData: { data: OrderDetailResponse } | OrderDetailResponse | undefined) => {
              if (!oldData) return oldData;

              // Handle both wrapped and unwrapped response types
              const orderData = "data" in oldData ? oldData.data : oldData;

              const updatedOrderData = {
                ...orderData,
                line_items: orderData.line_items.map((li) => ({
                  ...li,
                  images: li.images.map((img) =>
                    img.id === imageEvent.image_id ? imageData : img
                  ),
                })),
              };

              // Return in the same shape as the input
              return "data" in oldData ? { ...oldData, data: updatedOrderData } : updatedOrderData;
            }
          );
        } catch (error) {
          console.error("[Mercure] Failed to fetch image:", error);
          // Fallback: invalidate the whole order query
          queryClient.invalidateQueries({ queryKey: getGetOrderQueryKey(orderId) });
        }
      } else {
        // For order_update events or list_update: invalidate to trigger full refetch
        queryClient.invalidateQueries({ queryKey: getGetOrderQueryKey(orderId) });

        // Also invalidate the orders list in case status changed
        queryClient.invalidateQueries({ queryKey: getListOrdersQueryKey() });
      }
    },
    [orderId]
  );

  useMercure(`orders/${orderId}`, handleMessage, Boolean(orderId));
}
