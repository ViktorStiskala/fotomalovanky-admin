// Environment-based configuration
// VITE_API_URL is the base URL for API requests (without /api/v1 suffix)
// The Orval-generated code already includes /api/v1 in paths
// e.g., "" for local dev with proxy, "http://backend:8000" for Docker
export const API_URL = import.meta.env.VITE_API_URL || "";

export const MERCURE_URL =
  import.meta.env.VITE_MERCURE_URL || "http://localhost:3000/.well-known/mercure";
export const SHOPIFY_STORE_HANDLE = import.meta.env.VITE_SHOPIFY_STORE_HANDLE || "";

// Base URLs
export const SHOPIFY_ADMIN_BASE_URL = "https://admin.shopify.com/store";
