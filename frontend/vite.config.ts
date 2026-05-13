import path from "node:path";
import { fileURLToPath } from "node:url";

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Vite proxies /api/* to the FastAPI backend during development so that the
// frontend can call relative paths without hitting CORS.  In production the
// bundle is served by whatever host the user configures (nginx / static host)
// and VITE_API_BASE_URL is used instead.
const __dirname = path.dirname(fileURLToPath(import.meta.url));

export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
  server: {
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
      // Legacy /dashboard/* endpoints (still serving the HTML dashboard).
      "/dashboard": {
        target: "http://localhost:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
