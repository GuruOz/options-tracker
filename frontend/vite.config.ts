import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// Dev server proxies /api and /ws to the backend so the browser stays
// single-origin, mirroring nginx in production.
export default defineConfig({
  plugins: [react()],
  server: {
    proxy: {
      "/api": "http://localhost:8000",
      "/ws": { target: "ws://localhost:8000", ws: true },
    },
  },
});
