/**
 * Mercure SSE event data structure
 */
export interface MercureEvent {
  type: "order_update" | "list_update";
  order_number?: string;
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

/**
 * Processing status display configuration (for coloring/SVG generation)
 */
export const PROCESSING_STATUS_DISPLAY: Record<string, { label: string; color: string }> = {
  pending: { label: "Čeká", color: "bg-gray-100 text-gray-800" },
  queued: { label: "Ve frontě", color: "bg-blue-100 text-blue-800" },
  processing: { label: "Zpracovává se...", color: "bg-yellow-100 text-yellow-800" },
  completed: { label: "Dokončeno", color: "bg-green-100 text-green-800" },
  error: { label: "Chyba", color: "bg-red-100 text-red-800" },
};

/**
 * Get processing status display info
 */
export function getProcessingStatusDisplay(status: string | null): {
  label: string;
  color: string;
} {
  if (!status) return { label: "—", color: "" };
  return PROCESSING_STATUS_DISPLAY[status] || { label: status, color: "bg-gray-100 text-gray-800" };
}

/**
 * Payment status display configuration (from Shopify displayFinancialStatus)
 */
export const PAYMENT_STATUS_DISPLAY: Record<string, { label: string; color: string }> = {
  PENDING: { label: "Čeká na platbu", color: "bg-yellow-100 text-yellow-800" },
  AUTHORIZED: { label: "Autorizováno", color: "bg-blue-100 text-blue-800" },
  PARTIALLY_PAID: { label: "Částečně zaplaceno", color: "bg-orange-100 text-orange-800" },
  PAID: { label: "Zaplaceno", color: "bg-green-100 text-green-800" },
  PARTIALLY_REFUNDED: { label: "Částečně vráceno", color: "bg-purple-100 text-purple-800" },
  REFUNDED: { label: "Vráceno", color: "bg-gray-100 text-gray-800" },
  VOIDED: { label: "Zrušeno", color: "bg-red-100 text-red-800" },
  EXPIRED: { label: "Vypršelo", color: "bg-gray-100 text-gray-800" },
};

/**
 * Get payment status display info
 */
export function getPaymentStatusDisplay(status: string | null): { label: string; color: string } {
  if (!status) return { label: "—", color: "" };
  return PAYMENT_STATUS_DISPLAY[status] || { label: status, color: "bg-gray-100 text-gray-800" };
}
