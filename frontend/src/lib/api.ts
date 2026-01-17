import { API_URL, SHOPIFY_STORE_HANDLE, SHOPIFY_ADMIN_BASE_URL } from "./config";

// =============================================================================
// API Helper
// =============================================================================

interface ApiOptions extends RequestInit {
  params?: Record<string, string | number>;
}

/**
 * Typed fetch wrapper for API calls.
 * Automatically prepends API_URL and handles errors.
 */
async function api<T>(endpoint: string, options: ApiOptions = {}): Promise<T> {
  const { params, ...fetchOptions } = options;

  let url = `${API_URL}${endpoint}`;
  if (params) {
    const searchParams = new URLSearchParams();
    for (const [key, value] of Object.entries(params)) {
      searchParams.set(key, String(value));
    }
    url += `?${searchParams.toString()}`;
  }

  const response = await fetch(url, fetchOptions);
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Request failed" }));
    throw new Error(error.detail || "Request failed");
  }
  return response.json();
}

// =============================================================================
// URL Helpers
// =============================================================================

export function getShopifyOrderUrl(shopifyId: number): string {
  return `${SHOPIFY_ADMIN_BASE_URL}/${SHOPIFY_STORE_HANDLE}/orders/${shopifyId}`;
}

// =============================================================================
// Types
// =============================================================================

export interface Order {
  id: number;
  shopify_id: number;
  shopify_order_number: string;
  customer_email: string | null;
  customer_name: string | null;
  payment_status: string | null;
  status: OrderStatus;
  item_count: number;
  created_at: string;
}

export type OrderStatus = "pending" | "downloading" | "processing" | "ready_for_review" | "error";

// Coloring processing statuses
export type ColoringProcessingStatus =
  | "pending"
  | "queued"
  | "processing"
  | "runpod_submitting"
  | "runpod_submitted"
  | "runpod_queued"
  | "runpod_processing"
  | "completed"
  | "error";

// SVG processing statuses
export type SvgProcessingStatus =
  | "pending"
  | "queued"
  | "processing"
  | "vectorizer_processing"
  | "completed"
  | "error";

export interface OrderListResponse {
  orders: Order[];
  total: number;
}

// Options interfaces
export interface ColoringOptions {
  megapixels: number;
  steps: number;
}

export interface SvgOptions {
  shape_stacking: string;
  group_by: string;
}

// Version interfaces
export interface ColoringVersion {
  id: number;
  version: number;
  url: string | null;
  status: ColoringProcessingStatus;
  options: ColoringOptions;
  created_at: string;
}

export interface SvgVersion {
  id: number;
  version: number;
  url: string | null;
  status: SvgProcessingStatus;
  coloring_version_id: number;
  options: SvgOptions;
  created_at: string;
}

export interface Versions {
  coloring: ColoringVersion[];
  svg: SvgVersion[];
}

export interface SelectedVersionIds {
  coloring: number | null;
  svg: number | null;
}

export interface OrderImage {
  id: number;
  position: number;
  url: string | null;
  downloaded_at: string | null;
  selected_version_ids: SelectedVersionIds;
  versions: Versions;
}

export interface LineItem {
  id: number;
  title: string;
  quantity: number;
  dedication: string | null;
  layout: string | null;
  images: OrderImage[];
}

export interface OrderDetail {
  id: number;
  shopify_id: number;
  shopify_order_number: string;
  customer_email: string | null;
  customer_name: string | null;
  payment_status: string | null;
  shipping_method: string | null;
  status: OrderStatus;
  created_at: string;
  line_items: LineItem[];
}

// Generation settings
export interface ColoringSettings {
  megapixels?: number;
  steps?: number;
}

export interface SvgSettings {
  shape_stacking?: string;
  group_by?: string;
}

// =============================================================================
// Order API Functions
// =============================================================================

/**
 * Fetch list of orders with pagination
 */
export async function fetchOrders(skip = 0, limit = 50): Promise<OrderListResponse> {
  return api<OrderListResponse>("/orders", { params: { skip, limit } });
}

/**
 * Extract the order number from Shopify order number (e.g., "1270" from "#1270")
 */
export function extractOrderNumber(shopifyOrderNumber: string): string {
  return shopifyOrderNumber.replace(/^#/, "");
}

/**
 * Fetch a single order with line items and images by order number
 */
export async function fetchOrder(orderNumber: string): Promise<OrderDetail> {
  return api<OrderDetail>(`/orders/${orderNumber}`);
}

/**
 * Fetch a single image with all coloring/SVG versions
 * Used for efficient updates when receiving image_status Mercure events
 */
export async function fetchImage(orderNumber: string, imageId: number): Promise<OrderImage> {
  return api<OrderImage>(`/orders/${orderNumber}/images/${imageId}`);
}

/**
 * Trigger a manual sync/re-processing of an order
 */
export async function syncOrder(orderNumber: string): Promise<{ status: string; message: string }> {
  return api<{ status: string; message: string }>(`/orders/${orderNumber}/sync`, {
    method: "POST",
  });
}

export interface FetchFromShopifyResponse {
  status: string;
  message: string;
}

/**
 * Queue a background task to fetch recent orders from Shopify.
 * The actual import happens asynchronously - progress is pushed via Mercure updates.
 */
export async function fetchFromShopify(limit = 20): Promise<FetchFromShopifyResponse> {
  return api<FetchFromShopifyResponse>("/orders/fetch-from-shopify", {
    method: "POST",
    params: { limit },
  });
}

// =============================================================================
// Coloring Generation
// =============================================================================

export interface GenerateColoringResponse {
  queued: number;
  message: string;
}

/**
 * Generate coloring books for all images in an order
 */
export async function generateOrderColoring(
  orderNumber: string,
  settings?: ColoringSettings
): Promise<GenerateColoringResponse> {
  return api<GenerateColoringResponse>(`/orders/${orderNumber}/generate-coloring`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: settings ? JSON.stringify(settings) : undefined,
  });
}

/**
 * Generate a coloring book for a single image
 */
export async function generateImageColoring(
  imageId: number,
  settings?: ColoringSettings
): Promise<ColoringVersion> {
  return api<ColoringVersion>(`/images/${imageId}/generate-coloring`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: settings ? JSON.stringify(settings) : undefined,
  });
}

// =============================================================================
// SVG Generation
// =============================================================================

export interface GenerateSvgResponse {
  queued: number;
  message: string;
}

/**
 * Generate SVGs for all images in an order that have coloring versions
 */
export async function generateOrderSvg(
  orderNumber: string,
  settings?: SvgSettings
): Promise<GenerateSvgResponse> {
  return api<GenerateSvgResponse>(`/orders/${orderNumber}/generate-svg`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: settings ? JSON.stringify(settings) : undefined,
  });
}

/**
 * Generate an SVG for a single image
 */
export async function generateImageSvg(
  imageId: number,
  settings?: SvgSettings
): Promise<SvgVersion> {
  return api<SvgVersion>(`/images/${imageId}/generate-svg`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: settings ? JSON.stringify(settings) : undefined,
  });
}

// =============================================================================
// Version Management
// =============================================================================

/**
 * List all coloring versions for an image
 */
export async function listColoringVersions(imageId: number): Promise<ColoringVersion[]> {
  return api<ColoringVersion[]>(`/images/${imageId}/coloring-versions`);
}

/**
 * List all SVG versions for an image
 */
export async function listSvgVersions(imageId: number): Promise<SvgVersion[]> {
  return api<SvgVersion[]>(`/images/${imageId}/svg-versions`);
}

/**
 * Select a coloring version as the default for an image
 */
export async function selectColoringVersion(
  imageId: number,
  versionId: number
): Promise<{ status: string; message: string }> {
  return api<{ status: string; message: string }>(
    `/images/${imageId}/select-coloring/${versionId}`,
    { method: "PUT" }
  );
}

/**
 * Select an SVG version as the default for an image
 */
export async function selectSvgVersion(
  imageId: number,
  versionId: number
): Promise<{ status: string; message: string }> {
  return api<{ status: string; message: string }>(`/images/${imageId}/select-svg/${versionId}`, {
    method: "PUT",
  });
}

// =============================================================================
// Retry Failed Versions
// =============================================================================

/**
 * Retry a failed coloring version generation
 */
export async function retryColoringVersion(versionId: number): Promise<ColoringVersion> {
  return api<ColoringVersion>(`/coloring-versions/${versionId}/retry`, {
    method: "POST",
  });
}

/**
 * Retry a failed SVG version generation
 */
export async function retrySvgVersion(versionId: number): Promise<SvgVersion> {
  return api<SvgVersion>(`/svg-versions/${versionId}/retry`, {
    method: "POST",
  });
}
