import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// ADR-0012 §(7): dev server (port 5173) → backend (port 8765) を proxy で接続。
// production build は FastAPI が静的配信するため同一オリジン。
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: {
      "/api": {
        target: "http://localhost:8765",
        changeOrigin: true,
        ws: true,
      },
    },
  },
  build: {
    outDir: "dist",
    sourcemap: true,
  },
});
