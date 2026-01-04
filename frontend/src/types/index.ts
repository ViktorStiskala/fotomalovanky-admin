/**
 * Mercure SSE event data structure
 */
export interface MercureEvent {
  type: "order_update" | "list_update";
  id?: number;
}

/**
 * Order status display configuration
 */
export const ORDER_STATUS_DISPLAY: Record<string, { label: string; color: string }> = {
  pending: { label: "Čeká na zpracování", color: "bg-gray-100 text-gray-800" },
  downloading: { label: "Stahování...", color: "bg-blue-100 text-blue-800" },
  processing: { label: "Zpracování...", color: "bg-yellow-100 text-yellow-800" },
  ready_for_review: { label: "Ke kontrole", color: "bg-green-100 text-green-800" },
  error: { label: "Chyba", color: "bg-red-100 text-red-800" },
};
