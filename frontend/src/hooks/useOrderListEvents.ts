import { useEffect, useRef } from "react";
import { queryClient } from "@/lib/queryClient";
import type { MercureEvent } from "@/types";

const MERCURE_URL = import.meta.env.VITE_MERCURE_URL || "http://localhost:3000/.well-known/mercure";

/**
 * Custom hook that subscribes to Mercure SSE events for the orders list.
 *
 * When an event is received, it invalidates the TanStack Query cache,
 * triggering a refetch of the orders list from the API.
 *
 * This implements the "Ping-to-Refetch" pattern:
 * 1. Backend publishes lightweight ping to Mercure
 * 2. Frontend receives ping via SSE
 * 3. Frontend invalidates query cache
 * 4. TanStack Query refetches fresh data from API
 */
export function useOrderListEvents(): void {
  const eventSourceRef = useRef<EventSource | null>(null);

  useEffect(() => {
    // Build Mercure subscription URL
    const url = new URL(MERCURE_URL);
    url.searchParams.append("topic", "orders");

    // Create EventSource connection
    const eventSource = new EventSource(url.toString());
    eventSourceRef.current = eventSource;

    eventSource.onmessage = (event: MessageEvent) => {
      try {
        const data: MercureEvent = JSON.parse(event.data);
        console.log("[Mercure] Order list event received:", data);

        // Invalidate the orders list query to trigger a refetch
        queryClient.invalidateQueries({ queryKey: ["orders"] });

        // If it's an update to a specific order, also invalidate that order's query
        if (data.type === "order_update" && data.order_number) {
          queryClient.invalidateQueries({ queryKey: ["order", data.order_number] });
        }
      } catch (error) {
        console.error("[Mercure] Failed to parse event:", error);
      }
    };

    eventSource.onerror = (error) => {
      console.error("[Mercure] EventSource error:", error);
      // EventSource will automatically try to reconnect
    };

    eventSource.onopen = () => {
      console.log("[Mercure] Connected to orders topic");
    };

    // Cleanup on unmount
    return () => {
      console.log("[Mercure] Disconnecting from orders topic");
      eventSource.close();
      eventSourceRef.current = null;
    };
  }, []);
}
