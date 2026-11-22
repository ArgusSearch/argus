import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// The API (`make api`, port 8000) serves the C5 routes at the root; the dev server proxies them.
const api = process.env.ARGUS_API ?? "http://127.0.0.1:8000";
// The extension routers (narrator, demo, agent) and the route table the agent probe reads come along.
const routes = ["/health", "/events", "/graph", "/incidents", "/notes", "/receipts", "/replay", "/digest", "/routes", "/bench", "/report", "/autonomy", "/settings", "/connections", "/demo", "/agent", "/openapi.json", "/sealed-run"];

// Libraries in chunks of their own: the page's code changes often, React and the graph renderer rarely.
const vendor = [
  { name: "react", test: /node_modules[\\/](react|react-dom|scheduler)[\\/]/ },
  { name: "xyflow", test: /node_modules[\\/]@xyflow[\\/]/ },
  { name: "three", test: /node_modules[\\/]three[\\/]/ },
];

export default defineConfig({
  plugins: [react()],
  build: {
    // three.js is one library of about 540 kB the 3D scene needs whole; it is only requested behind ?fx (GraphStage)
    chunkSizeWarningLimit: 640,
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
    proxy: Object.fromEntries(routes.map((r) => [r, { target: api, changeOrigin: r !== "/connections" }])),
  },
  test: { environment: "node" },
});
