import { expect, test } from "@playwright/test";
import { LIVE, health, incidentCard, openMissionControl, replay, watchErrors } from "./helpers";

test("pause stops the run, play resumes it", async ({ page, request }) => {
  const errors = watchErrors(page);
  if (!LIVE) await replay(request, { action: "restart", speed: 8 });
  await replay(request, { action: "play" });
  await openMissionControl(page);
  await expect(page.locator(".clock-time")).not.toHaveText("waiting for the first tick", { timeout: 15_000 });

  await page.locator(".controls").getByRole("button", { name: "Pause" }).click();
  await expect(page.locator(".controls").getByRole("button", { name: "Play" })).toBeVisible();
  const before = (await health(request)).run.position;
  const clock = await page.locator(".clock-time").innerText();
  await page.waitForTimeout(2500);
  expect((await health(request)).run.position).toBe(before);
  await expect(page.locator(".clock-time")).toHaveText(clock);

  await page.locator(".controls").getByRole("button", { name: "Play" }).click();
  await expect(page.locator(".controls").getByRole("button", { name: "Pause" })).toBeVisible();
  await expect.poll(async () => (await health(request)).run.position, { timeout: 15_000 }).toBeGreaterThan(before);
  expect(errors()).toEqual([]);
});

test("restart clears the feed and refills it without duplicates", async ({ page, request }) => {
  test.skip(LIVE, "restart is a replay control");
  const errors = watchErrors(page);
  await replay(request, { action: "restart", speed: 64 });
  await replay(request, { action: "play" });
  await openMissionControl(page);
  await expect(incidentCard(page)).toBeVisible({ timeout: 90_000 });
  const feedCount = async () => Number(await page.locator(".tabs .tab").first().locator(".count").innerText());
  await expect.poll(async () => (await health(request)).run.finished, { timeout: 60_000 }).toBe(true);
  const full = await feedCount();

  await page.locator(".controls").getByRole("button", { name: "Pause" }).click();
  await page.getByRole("button", { name: "Restart" }).click();
  await expect(incidentCard(page)).toHaveCount(0, { timeout: 10_000 });
  await expect.poll(feedCount, { timeout: 10_000 }).toBeLessThan(full);

  await replay(request, { speed: 64 });
  await replay(request, { action: "play" });
  await expect(incidentCard(page)).toHaveCount(1, { timeout: 90_000 });
  await expect.poll(async () => (await health(request)).run.finished, { timeout: 60_000 }).toBe(true);
  await page.waitForTimeout(1000);
  expect(await feedCount()).toBe(full);
  await expect(incidentCard(page)).toHaveCount(1);
  const keys = await page.locator(".feed article").evaluateAll((els) => els.map((e) => e.textContent ?? ""));
  expect(new Set(keys).size, "no two identical feed cards").toBe(keys.length);
  expect(errors()).toEqual([]);
});
