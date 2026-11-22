import { expect, test } from "@playwright/test";
import { LIVE, incidentCard, openMissionControl, replay } from "./helpers";

// One verdict, one label: the card pill, the graph tag, the trail's verdict step and the digest all say
// "SUPPORTED CAUSE" (#15), never the raw enum or a different name.
test("the S1 verdict is written the same way everywhere", async ({ page, request }) => {
  test.skip(LIVE, "replay-only: drives the recorded S1 run");
  await replay(request, { action: "restart", speed: 16 });
  await replay(request, { action: "play" });
  await openMissionControl(page);
  // fast to the incident, then slow so the verdict can be caught before the incident resolves
  await expect(incidentCard(page)).toBeVisible({ timeout: 90_000 });
  await replay(request, { speed: 1 });
  await expect(incidentCard(page).locator(".pill.SUPPORTED_CAUSE")).toHaveText("SUPPORTED CAUSE", { timeout: 30_000 });
  await replay(request, { action: "pause" });
  await expect(page.locator(".mnode-tag").filter({ hasText: /cause/i }).first()).toBeVisible();
  if (process.env.SHOT) await page.locator(".react-flow__node").filter({ has: page.locator(".mnode-tag") }).first().screenshot({ path: process.env.SHOT });

  const main = await page.locator(".app").innerText();
  expect(main, "raw enum on the page").not.toContain("SUPPORTED_CAUSE");
  expect(main.toLowerCase(), "a second name for the same verdict").not.toContain("root cause");

  await page.goto("/?view=report&fxintro=0");
  const digest = page.getByRole("region", { name: "morning report" });
  await expect(digest.locator(".mr-line").first()).toBeVisible();
  expect(await digest.innerText(), "raw enum in the digest").not.toContain("SUPPORTED_CAUSE");
});
