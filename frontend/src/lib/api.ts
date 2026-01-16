import { API_BASE, SHOPIFY_STORE_HANDLE, SHOPIFY_ADMIN_BASE_URL } from "./config";

// =============================================================================
// URL Helpers
// =============================================================================

export function getImageUrl(imageId: number): string {
  return `${API_BASE}/api/v1/images/${imageId}`;
}

export function getColoringVersionUrl(versionId: number): string {
  return `${API_BASE}/api/v1/coloring-versions/${versionId}/file`;
}

export function getSvgVersionUrl(versionId: number): string {
  return `${API_BASE}/api/v1/svg-versions/${versionId}/file`;
}

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

export type ProcessingStatus = "pending" | "queued" | "processing" | "completed" | "error";

export interface OrderListResponse {
  orders: Order[];
  total: number;
}

export interface SvgVersion {
  id: number;
  version: number;
  file_path: string | null;
  status: ProcessingStatus;
  coloring_version_id: number;
  shape_stacking: string;
  group_by: string;
  created_at: string;
}

export interface ColoringVersion {
  id: number;
  version: number;
  file_path: string | null;
  status: ProcessingStatus;
  megapixels: number;
  steps: number;
  created_at: string;
  svg_versions: SvgVersion[];
}

export interface OrderImage {
  id: number;
  position: number;
  original_url: string;
  local_path: string | null;
  downloaded_at: string | null;
  selected_coloring_id: number | null;
  selected_svg_id: number | null;
  coloring_versions: ColoringVersion[];
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

/**
 * Fetch list of orders with pagination
 */
export async function fetchOrders(skip = 0, limit = 50): Promise<OrderListResponse> {
  const response = await fetch(`${API_BASE}/api/v1/orders?skip=${skip}&limit=${limit}`);
  if (!response.ok) {
    throw new Error("Failed to fetch orders");
  }
  return response.json();
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
  const response = await fetch(`${API_BASE}/api/v1/orders/${orderNumber}`);
  if (!response.ok) {
    throw new Error("Failed to fetch order");
  }
  return response.json();
}

/**
 * Trigger a manual sync/re-processing of an order
 */
export async function syncOrder(orderNumber: string): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE}/api/v1/orders/${orderNumber}/sync`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error("Failed to sync order");
  }
  return response.json();
}

export interface FetchFromShopifyResponse {
  imported: number;
  updated: number;
  skipped: number;
  total: number;
}

/**
 * Fetch recent orders from Shopify and import them
 */
export async function fetchFromShopify(limit = 20): Promise<FetchFromShopifyResponse> {
  const response = await fetch(`${API_BASE}/api/v1/orders/fetch-from-shopify?limit=${limit}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error("Failed to fetch from Shopify");
  }
  return response.json();
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
  const response = await fetch(`${API_BASE}/api/v1/orders/${orderNumber}/generate-coloring`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: settings ? JSON.stringify(settings) : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to generate coloring" }));
    throw new Error(error.detail || "Failed to generate coloring");
  }
  return response.json();
}

/**
 * Generate a coloring book for a single image
 */
export async function generateImageColoring(
  imageId: number,
  settings?: ColoringSettings
): Promise<ColoringVersion> {
  const response = await fetch(`${API_BASE}/api/v1/images/${imageId}/generate-coloring`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: settings ? JSON.stringify(settings) : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to generate coloring" }));
    throw new Error(error.detail || "Failed to generate coloring");
  }
  return response.json();
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
  const response = await fetch(`${API_BASE}/api/v1/orders/${orderNumber}/generate-svg`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: settings ? JSON.stringify(settings) : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to generate SVG" }));
    throw new Error(error.detail || "Failed to generate SVG");
  }
  return response.json();
}

/**
 * Generate an SVG for a single image
 */
export async function generateImageSvg(
  imageId: number,
  settings?: SvgSettings
): Promise<SvgVersion> {
  const response = await fetch(`${API_BASE}/api/v1/images/${imageId}/generate-svg`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: settings ? JSON.stringify(settings) : undefined,
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to generate SVG" }));
    throw new Error(error.detail || "Failed to generate SVG");
  }
  return response.json();
}

// =============================================================================
// Version Management
// =============================================================================

/**
 * List all coloring versions for an image
 */
export async function listColoringVersions(imageId: number): Promise<ColoringVersion[]> {
  const response = await fetch(`${API_BASE}/api/v1/images/${imageId}/coloring-versions`);
  if (!response.ok) {
    throw new Error("Failed to list coloring versions");
  }
  return response.json();
}

/**
 * List all SVG versions for an image
 */
export async function listSvgVersions(imageId: number): Promise<SvgVersion[]> {
  const response = await fetch(`${API_BASE}/api/v1/images/${imageId}/svg-versions`);
  if (!response.ok) {
    throw new Error("Failed to list SVG versions");
  }
  return response.json();
}

/**
 * Select a coloring version as the default for an image
 */
export async function selectColoringVersion(
  imageId: number,
  versionId: number
): Promise<{ status: string; message: string }> {
  const response = await fetch(
    `${API_BASE}/api/v1/images/${imageId}/select-coloring/${versionId}`,
    { method: "POST" }
  );
  if (!response.ok) {
    throw new Error("Failed to select coloring version");
  }
  return response.json();
}

/**
 * Select an SVG version as the default for an image
 */
export async function selectSvgVersion(
  imageId: number,
  versionId: number
): Promise<{ status: string; message: string }> {
  const response = await fetch(`${API_BASE}/api/v1/images/${imageId}/select-svg/${versionId}`, {
    method: "POST",
  });
  if (!response.ok) {
    throw new Error("Failed to select SVG version");
  }
  return response.json();
}

// =============================================================================
// Retry Failed Versions
// =============================================================================

/**
 * Retry a failed coloring version generation
 */
export async function retryColoringVersion(versionId: number): Promise<ColoringVersion> {
  const response = await fetch(`${API_BASE}/api/v1/coloring-versions/${versionId}/retry`, {
    method: "POST",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to retry coloring" }));
    throw new Error(error.detail || "Failed to retry coloring");
  }
  return response.json();
}

/**
 * Retry a failed SVG version generation
 */
export async function retrySvgVersion(versionId: number): Promise<SvgVersion> {
  const response = await fetch(`${API_BASE}/api/v1/svg-versions/${versionId}/retry`, {
    method: "POST",
  });
  if (!response.ok) {
    const error = await response.json().catch(() => ({ detail: "Failed to retry SVG" }));
    throw new Error(error.detail || "Failed to retry SVG");
  }
  return response.json();
}
