import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The API (`make api`, port 8000) serves the C5 routes at the root; the dev server proxies them.
const api = process.env.ARGUS_API ?? "http://127.0.0.1:8000";
const routes = ["/health", "/events", "/graph", "/incidents", "/notes", "/receipts", "/replay", "/digest"];

// Libraries in chunks of their own: the page's code changes often, React and the graph renderer rarely.
const vendor = [
  { name: "react", test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
  { name: "xyflow", test: /node_modules[\\/]@xyflow[\\/]/ },
];

export default defineConfig({
  plugins: [react()],
  build: {
    rolldownOptions: {
      output: { codeSplitting: { groups: vendor } },
      onLog(level, log, handler) {
        // react-compiler-runtime (via @xyflow) marks itself "use no memo", a hint only its compiler reads.
        if (log.code === "MODULE_LEVEL_DIRECTIVE" && log.id?.includes("node_modules")) return;
        handler(level, log);
      },
    },
  },
  server: {
    port: 5173,
    proxy: Object.fromEntries(routes.map((r) => [r, { target: api, changeOrigin: true }])),
  },
  test: { environment: "node" },
});
