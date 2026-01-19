// MercureEvent types are now generated from the backend schema.
// Import from @/api/generated/schemas:
// import type { ImageStatusEvent, ImageUpdateEvent, ListUpdateEvent, OrderUpdateEvent } from "@/api/generated/schemas";

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
 * Coloring processing status display configuration (RunPod workflow)
 */
export const COLORING_STATUS_DISPLAY: Record<string, { label: string; color: string }> = {
  pending: { label: "Čeká na odeslání", color: "bg-gray-100 text-gray-800" },
  queued: { label: "Čeká ve frontě", color: "bg-blue-100 text-blue-800" },
  processing: { label: "Zpracovává se...", color: "bg-blue-100 text-blue-800" },
  runpod_submitting: { label: "Runpod: odesílání na server", color: "bg-blue-100 text-blue-800" },
  runpod_submitted: { label: "Runpod: úloha přijata", color: "bg-blue-100 text-blue-800" },
  runpod_queued: { label: "Runpod: čeká ve frontě", color: "bg-yellow-100 text-yellow-800" },
  runpod_processing: {
    label: "Runpod: Probíhá zpracování",
    color: "bg-yellow-100 text-yellow-800",
  },
  runpod_completed: { label: "Runpod: dokončeno", color: "bg-green-100 text-green-800" },
  storage_upload: { label: "Nahrávání na S3", color: "bg-blue-100 text-blue-800" },
  completed: { label: "Dokončeno", color: "bg-green-100 text-green-800" },
  error: { label: "Chyba", color: "bg-red-100 text-red-800" },
  runpod_cancelled: { label: "Runpod: Zrušeno", color: "bg-orange-100 text-orange-800" },
};

/**
 * SVG processing status display configuration (Vectorizer.ai workflow)
 */
export const SVG_STATUS_DISPLAY: Record<string, { label: string; color: string }> = {
  pending: { label: "Čeká na odeslání", color: "bg-gray-100 text-gray-800" },
  queued: { label: "Čeká ve frontě", color: "bg-blue-100 text-blue-800" },
  processing: { label: "Zpracovává se...", color: "bg-blue-100 text-blue-800" },
  vectorizer_processing: {
    label: "Vectorizer: Probíhá zpracování",
    color: "bg-yellow-100 text-yellow-800",
  },
  vectorizer_completed: { label: "Vectorizer: dokončeno", color: "bg-green-100 text-green-800" },
  storage_upload: { label: "Nahrávání na S3", color: "bg-blue-100 text-blue-800" },
  completed: { label: "Dokončeno", color: "bg-green-100 text-green-800" },
  error: { label: "Chyba", color: "bg-red-100 text-red-800" },
};

/**
 * Get coloring status display info
 */
export function getColoringStatusDisplay(status: string | null): {
  label: string;
  color: string;
} {
  if (!status) return { label: "—", color: "" };
  return COLORING_STATUS_DISPLAY[status] || { label: status, color: "bg-gray-100 text-gray-800" };
}

/**
 * Get SVG status display info
 */
export function getSvgStatusDisplay(status: string | null): {
  label: string;
  color: string;
} {
  if (!status) return { label: "—", color: "" };
  return SVG_STATUS_DISPLAY[status] || { label: status, color: "bg-gray-100 text-gray-800" };
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

// =============================================================================
// SVG Options Label Helpers
// =============================================================================

/**
 * Shape stacking option labels (Czech)
 */
export const SHAPE_STACKING_LABELS: Record<string, string> = {
  stacked: "Vrstvené",
  none: "Žádné",
};

/**
 * Group by option labels (Czech)
 */
export const GROUP_BY_LABELS: Record<string, string> = {
  color: "Podle barvy",
  none: "Žádné",
};

/**
 * Get localized label for shape stacking option.
 */
export function getShapeStackingLabel(value: string): string {
  return SHAPE_STACKING_LABELS[value] || value;
}

/**
 * Get localized label for group by option.
 */
export function getGroupByLabel(value: string): string {
  return GROUP_BY_LABELS[value] || value;
}
