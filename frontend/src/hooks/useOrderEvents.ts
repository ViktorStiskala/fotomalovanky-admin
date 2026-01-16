import { useCallback } from "react";
import { queryClient } from "@/lib/queryClient";
import { useMercure } from "./useMercure";
import { fetchImage, OrderDetail, OrderImage } from "@/lib/api";
import type { MercureEvent } from "@/types";

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
 * @param orderNumber - The Shopify order number (e.g., "1270")
 */
export function useOrderEvents(orderNumber: string): void {
  const handleMessage = useCallback(
    async (data: unknown) => {
      const event = data as MercureEvent;
      console.log(`[Mercure] Order ${orderNumber} event received:`, event);

      if ((event.type === "image_status" || event.type === "image_update") && event.image_id) {
        // Efficient update: fetch only the updated image
        try {
          const imageData = await fetchImage(orderNumber, event.image_id);

          // Update the cache by replacing just this image in the order data
          queryClient.setQueryData<OrderDetail>(["order", orderNumber], (oldData) => {
            if (!oldData) return oldData;

            return {
              ...oldData,
              line_items: oldData.line_items.map((li) => ({
                ...li,
                images: li.images.map((img: OrderImage) =>
                  img.id === event.image_id ? imageData : img
                ),
              })),
            };
          });
        } catch (error) {
          console.error("[Mercure] Failed to fetch image:", error);
          // Fallback: invalidate the whole order query
          queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });
        }
      } else {
        // For order_update events or unknown types: invalidate to trigger full refetch
        queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });

        // Also invalidate the orders list in case status changed
        queryClient.invalidateQueries({ queryKey: ["orders"] });
      }
    },
    [orderNumber]
  );

  useMercure(`orders/${orderNumber}`, handleMessage, !!orderNumber);
}
