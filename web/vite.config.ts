import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The API (`make api`, port 8000) serves the C5 routes at the root; the dev server proxies them.
const api = process.env.ARGUS_API ?? "http://127.0.0.1:8000";
const routes = ["/health", "/events", "/graph", "/incidents", "/notes", "/receipts", "/replay", "/digest"];

export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    proxy: Object.fromEntries(routes.map((r) => [r, { target: api, changeOrigin: true }])),
  },
  test: { environment: "node" },
});
