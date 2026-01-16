import { useCallback } from "react";
import { queryClient } from "@/lib/queryClient";
import { useMercure } from "./useMercure";
import type { MercureEvent } from "@/types";

/**
 * Custom hook that subscribes to Mercure SSE events for a specific order.
 *
 * When an event is received for this order, it invalidates the TanStack Query cache,
 * triggering a refetch of the order detail from the API.
 *
 * This enables real-time status updates as background workers process the order:
 * - pending → downloading → processing → ready_for_review
 *
 * @param orderNumber - The Shopify order number (e.g., "1270")
 */
export function useOrderEvents(orderNumber: string): void {
  const handleMessage = useCallback(
    (data: unknown) => {
      const event = data as MercureEvent;
      console.log(`[Mercure] Order ${orderNumber} event received:`, event);

      // Invalidate this specific order's query to trigger a refetch
      queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });

      // Also invalidate the orders list in case status changed
      queryClient.invalidateQueries({ queryKey: ["orders"] });
    },
    [orderNumber]
  );

  useMercure(`orders/${orderNumber}`, handleMessage, !!orderNumber);
}
