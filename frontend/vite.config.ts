import path from "path";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";
import { iconSpritePlugin } from "./scripts/iconSpritePlugin";

export default defineConfig({
  plugins: [react(), iconSpritePlugin()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    host: true,
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
});
