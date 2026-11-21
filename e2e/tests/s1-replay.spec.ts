import { expect, test } from "@playwright/test";
import { LIVE, incidentCard, openIncident, replay, watchErrors, openMissionControl } from "./helpers";

test("S1: INC-0001 is a supported cause in DE / android / PayCo with the release ruled out", async ({ page, request, context }) => {
  test.skip(LIVE, "replay-only: live mode is covered by receipt.spec");
  const errors = watchErrors(page);
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await replay(request, { action: "restart" });
  await replay(request, { action: "play" });
  await openMissionControl(page);

  // the fastest option the page offers
  await page.locator(".controls").getByRole("button", { name: "8×" }).click();
  await expect(page.locator(".controls").getByRole("button", { name: "8×" })).toHaveClass(/\bon\b/);

  const card = incidentCard(page);
  await expect(card).toBeVisible({ timeout: 90_000 });
  await expect(card.locator(".pill.SUPPORTED_CAUSE")).toHaveText("SUPPORTED CAUSE", { timeout: 60_000 });
  await expect(card.locator(".segs")).toContainText("DE");
  await expect(card.locator(".segs")).toContainText("android");
  await expect(card.locator(".segs")).toContainText("PayCo");
  await expect(card).toHaveCount(1);

  const sheet = await openIncident(page);
  await expect(sheet.locator(".sheet-top .pill.SUPPORTED_CAUSE")).toHaveText("SUPPORTED CAUSE");
  await expect(sheet.locator(".sheet-title")).toContainText("PayCo");
  const ruled = sheet.locator(".ruled");
  await expect(ruled).toContainText(/android-app 8\.3\.0/);

  await sheet.getByRole("button", { name: "Copy report (Markdown)" }).click();
  await expect(sheet.getByRole("button", { name: "Copied" })).toBeVisible();
  const md = await page.evaluate(() => navigator.clipboard.readText());
  expect(md).toContain("SUPPORTED CAUSE");
  expect(md).toContain("INC-0001");
  expect(md).toContain("PayCo");

  const report = await request.get("/incidents/INC-0001/report");
  expect(report.ok()).toBeTruthy();
  expect(await report.text()).toContain("## What happened");
  expect(errors()).toEqual([]);
});
