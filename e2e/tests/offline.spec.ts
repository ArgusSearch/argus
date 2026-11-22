import { expect, test } from "@playwright/test";
import { isUp, startApi, stopApi, type OwnApi } from "./own-api";

// This spec runs its own replay API on a separate port so it can stop it without touching the shared server.
// Every wait is bounded and the server is stopped in afterEach, so a failure never leaves port 8012 busy.
const PORT = Number(process.env.ARGUS_E2E_OFFLINE_PORT ?? 8012);
const BASE = `http://127.0.0.1:${PORT}`;

// The running server lives at module level so afterEach can stop it even when the test times out
// (a timed-out test body never reaches its own `finally`).
let api: OwnApi | null = null;
test.afterEach(async () => {
  await stopApi(api);
  api = null;
});

test("stopping the API shows the offline banner; starting it again recovers without a reload", async ({ page }) => {
  // Known app bug: with the connection refused the browser keeps the EventSource in CONNECTING and retries
  // forever, so web/src/lib/api.ts never reports "offline"; the header falls back to the last mode and keeps
  // saying "Example shop history". Observed 5 s and 30 s after the stop: no banner, header unchanged.
  test.setTimeout(90_000);

  api = await startApi(PORT);
  await page.goto(BASE);
  await expect(page.locator(".header .mode")).toHaveText("Example shop history", { timeout: 10_000 });
  await expect(page.locator(".banner")).toHaveCount(0);

  await stopApi(api);
  api = null;
  expect(await isUp(BASE), `API on ${PORT} stopped`).toBe(false);
  await expect(page.locator(".banner")).toContainText("The API is offline", { timeout: 15_000 });
  await expect(page.locator(".header .mode")).toHaveText("API offline");

  api = await startApi(PORT);
  await expect(page.locator(".banner")).toHaveCount(0, { timeout: 30_000 });
  await expect(page.locator(".header .mode")).toHaveText("Example shop history");
});
