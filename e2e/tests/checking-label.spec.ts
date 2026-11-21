import { expect, test } from "@playwright/test";
import { LIVE, incidentCard, openMissionControl, replay } from "./helpers";

// The graph bar says "checking <metric>" while an investigation runs; after the verdict it must go (#13).
test("the 'checking' label goes away once the incident has its verdict", async ({ page, request }) => {
  test.skip(LIVE, "replay-only: drives the recorded S1 run");
  // remove test.fail once the fix for #13 (PR #41) is on main
  test.fail(true, "stale 'checking' label: https://github.com/ArgusSearch/argus/issues/13");
  await replay(request, { action: "restart", speed: 8 });
  await replay(request, { action: "play" });
  await openMissionControl(page);
  await expect(page.locator(".graph-bar .checking")).toContainText("checking", { timeout: 90_000 });
  await expect(incidentCard(page).locator(".pill.SUPPORTED_CAUSE")).toBeVisible({ timeout: 60_000 });
  await replay(request, { action: "pause" });
  await expect(page.locator(".graph-bar .checking")).toHaveCount(0, { timeout: 5_000 });
});
