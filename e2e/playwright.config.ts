import { defineConfig, devices } from "@playwright/test";

// Replay mode (default) streams fixtures/ through the real SSE path; live mode runs Argus over an S1 world.
// The replay is global server state (play, pause, speed, restart), so the specs run one at a time.
const live = process.env.ARGUS_E2E_MODE === "live";
const port = Number(process.env.ARGUS_E2E_PORT ?? (live ? 8011 : 8010));
const world = process.env.ARGUS_E2E_WORLD ?? "runs/s1-7/world.duckdb";
const command = live
  ? `uv run argus api --port ${port} --world ${world} --tick-seconds 0.2`
  : `uv run argus api --port ${port}`;

export default defineConfig({
  testDir: "./tests",
  fullyParallel: false,
  workers: 1,
  retries: 0,
  timeout: 120_000,
  expect: { timeout: 10_000 },
  reporter: process.env.CI ? [["list"], ["html", { open: "never" }]] : [["list"]],
  use: {
    baseURL: `http://127.0.0.1:${port}`,
    viewport: { width: 1440, height: 900 },
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
  },
  projects: [{ name: live ? "live" : "replay", use: { ...devices["Desktop Chrome"], viewport: { width: 1440, height: 900 } } }],
  webServer: {
    command,
    cwd: "..",
    url: `http://127.0.0.1:${port}/health`,
    reuseExistingServer: !process.env.CI,
    timeout: 60_000,
    stdout: "ignore",
    stderr: "pipe",
  },
});
