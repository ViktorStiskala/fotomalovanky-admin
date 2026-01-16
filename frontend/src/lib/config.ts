// Environment-based configuration
// VITE_API_URL should contain the full base URL including /api/v1
// e.g., http://localhost:8000/api/v1 or http://backend:8000/api/v1
export const API_URL = import.meta.env.VITE_API_URL || "/api/v1";

// Legacy alias for backward compatibility (deprecated)
export const API_BASE = import.meta.env.VITE_API_URL
  ? import.meta.env.VITE_API_URL.replace(/\/api\/v1$/, "")
  : "";

export const MERCURE_URL =
  import.meta.env.VITE_MERCURE_URL || "http://localhost:3000/.well-known/mercure";
export const SHOPIFY_STORE_HANDLE = import.meta.env.VITE_SHOPIFY_STORE_HANDLE || "";

// Base URLs
export const SHOPIFY_ADMIN_BASE_URL = "https://admin.shopify.com/store";
