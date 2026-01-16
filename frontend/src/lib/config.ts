// Environment-based configuration
export const API_BASE = import.meta.env.VITE_API_URL || "";
export const MERCURE_URL =
  import.meta.env.VITE_MERCURE_URL || "http://localhost:3000/.well-known/mercure";
export const SHOPIFY_STORE_HANDLE = import.meta.env.VITE_SHOPIFY_STORE_HANDLE || "";

// Base URLs
export const SHOPIFY_ADMIN_BASE_URL = "https://admin.shopify.com/store";
