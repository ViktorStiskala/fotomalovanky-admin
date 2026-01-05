import { useEffect, useRef } from "react";
import { queryClient } from "@/lib/queryClient";
import type { MercureEvent } from "@/types";

const MERCURE_URL = import.meta.env.VITE_MERCURE_URL || "http://localhost:3000/.well-known/mercure";

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
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    if (!orderNumber) {
      return;
    }

    // Build Mercure subscription URL for this specific order
    const url = new URL(MERCURE_URL);
    url.searchParams.append("topic", `orders/${orderNumber}`);

    // Create EventSource connection
    const eventSource = new EventSource(url.toString());
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event: MessageEvent) => {
      try {
        const data: MercureEvent = JSON.parse(event.data);
        console.log(`[Mercure] Order ${orderNumber} event received:`, data);

        // Invalidate this specific order's query to trigger a refetch
        queryClient.invalidateQueries({ queryKey: ["order", orderNumber] });

        // Also invalidate the orders list in case status changed
        queryClient.invalidateQueries({ queryKey: ["orders"] });
      } catch (error) {
        console.error("[Mercure] Failed to parse event:", error);
      }
    };

    eventSource.onerror = (error) => {
      console.error(`[Mercure] EventSource error for order ${orderNumber}:`, error);
      // EventSource will automatically try to reconnect
    };

    eventSource.onopen = () => {
      console.log(`[Mercure] Connected to order ${orderNumber} topic`);
    };

    // Cleanup on unmount or when orderNumber changes
    return () => {
      console.log(`[Mercure] Disconnecting from order ${orderNumber} topic`);
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, [orderNumber]);
}
