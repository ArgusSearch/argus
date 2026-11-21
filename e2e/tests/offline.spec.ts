import { spawn, type ChildProcess } from "node:child_process";
import { expect, test } from "@playwright/test";

// This spec runs its own replay API on a separate port so it can stop it without touching the shared server.
// Every wait is bounded and the server is stopped in `finally`, so a failure never leaves port 8012 busy.
const PORT = Number(process.env.ARGUS_E2E_OFFLINE_PORT ?? 8012);
const BASE = `http://127.0.0.1:${PORT}`;
const sleep = (ms: number) => new Promise((r) => setTimeout(r, ms));

async function isUp(): Promise<boolean> {
  try {
    return (await fetch(`${BASE}/health`, { signal: AbortSignal.timeout(1000) })).ok;
  } catch {
    return false;
  }
}

async function start(): Promise<ChildProcess> {
  if (await isUp()) throw new Error(`port ${PORT} is already serving: stop it first (pkill -f "argus api --port ${PORT}")`);
  const proc = spawn("uv", ["run", "argus", "api", "--port", String(PORT)], { cwd: "..", stdio: "ignore", detached: true });
  for (let i = 0; i < 120; i++) {
    if (await isUp()) return proc;
    if (proc.exitCode !== null) break;
    await sleep(250);
  }
  await stop(proc);
  throw new Error(`API on ${PORT} did not start within 30 s`);
}

/** SIGINT the whole process group (uv and the Python child), then SIGKILL if the port is still open after 5 s. */
async function stop(proc: ChildProcess | null): Promise<void> {
  if (!proc?.pid) return;
  const signal = (sig: NodeJS.Signals) => {
    try {
      process.kill(-proc.pid!, sig);
    } catch {
      /* already gone */
    }
  };
  signal("SIGINT");
  for (let i = 0; i < 20; i++) {
    if (!(await isUp())) return;
    await sleep(250);
  }
  signal("SIGKILL");
}

// The running server lives at module level so afterEach can stop it even when the test times out
// (a timed-out test body never reaches its own `finally`).
let api: ChildProcess | null = null;
test.afterEach(async () => {
  await stop(api);
  api = null;
});

test("stopping the API shows the offline banner; starting it again recovers without a reload", async ({ page }) => {
  // Known app bug: with the connection refused the browser keeps the EventSource in CONNECTING and retries
  // forever, so web/src/lib/api.ts never reports "offline"; the header falls back to the last mode and keeps
  // saying "Replay · recorded run". Observed 5 s and 30 s after the stop: no banner, header unchanged.
  // remove test.fail once the offline-banner issue is fixed
  test.fail(true, "offline banner never shows: https://github.com/ArgusSearch/argus/issues/6");
  test.setTimeout(90_000);

  api = await start();
  try {
    await page.goto(BASE);
    await expect(page.locator(".header .mode")).toHaveText("Replay · recorded run", { timeout: 10_000 });
    await expect(page.locator(".banner")).toHaveCount(0);

    await stop(api);
    api = null;
    expect(await isUp(), `API on ${PORT} stopped`).toBe(false);
    await expect(page.locator(".banner")).toContainText("The API is offline", { timeout: 15_000 });
    await expect(page.locator(".header .mode")).toHaveText("API offline");

    api = await start();
    await expect(page.locator(".banner")).toHaveCount(0, { timeout: 30_000 });
    await expect(page.locator(".header .mode")).toHaveText("Replay · recorded run");
  } finally {
    await stop(api);
    api = null;
  }
});
