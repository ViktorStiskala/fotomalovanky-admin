import { useCallback } from "react";
import { queryClient } from "@/lib/queryClient";
import { useMercure } from "./useMercure";
import { getGetOrderQueryKey, getListOrdersQueryKey } from "@/api/generated/orders/orders";
import type { ListUpdateEvent } from "@/api/generated/schemas";

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
 *
 * ListUpdateEvent behavior:
 * - order_ids empty: Full refresh (Order was created/deleted)
 * - order_ids populated: Targeted refresh for specific orders
 */
export function useOrderListEvents(): void {
  const handleMessage = useCallback((data: unknown) => {
    const event = data as ListUpdateEvent;
    console.log("[Mercure] Order list event received:", event);

    // Only handle list_update events on "orders" topic
    if (event.type !== "list_update") {
      return;
    }

    // If order_ids is provided and non-empty, invalidate specific orders
    if (event.order_ids && event.order_ids.length > 0) {
      for (const orderId of event.order_ids) {
        queryClient.invalidateQueries({ queryKey: getGetOrderQueryKey(orderId) });
      }
    }
    // Always invalidate the orders list
    queryClient.invalidateQueries({ queryKey: getListOrdersQueryKey() });
  }, []);

  useMercure("orders", handleMessage);
}
