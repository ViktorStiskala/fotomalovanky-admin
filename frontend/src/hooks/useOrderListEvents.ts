import { useCallback } from "react";
import { queryClient } from "@/lib/queryClient";
import { useMercure } from "./useMercure";
import { getGetOrderQueryKey, getListOrdersQueryKey } from "@/api/generated/orders/orders";
import type {
  ImageStatusEvent,
  ImageUpdateEvent,
  ListUpdateEvent,
  OrderUpdateEvent,
} from "@/api/generated/schemas";

// Union type for all Mercure events
type MercureEvent = ImageStatusEvent | ImageUpdateEvent | ListUpdateEvent | OrderUpdateEvent;

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
 * Note: `image_status` events are ignored here as they only affect detail views.
 */
export function useOrderListEvents(): void {
  const handleMessage = useCallback((data: unknown) => {
    const event = data as MercureEvent;
    console.log("[Mercure] Order list event received:", event);

    // image_status events don't affect the list view
    if (event.type === "image_status") {
      return;
    }

    // Invalidate the orders list query to trigger a refetch
    queryClient.invalidateQueries({ queryKey: getListOrdersQueryKey() });

    // If it's an update to a specific order, also invalidate that order's query
    if (event.type === "order_update") {
      queryClient.invalidateQueries({
        queryKey: getGetOrderQueryKey(event.shopify_id),
      });
    }
  }, []);

  useMercure("orders", handleMessage);
}
