import { expect, test } from "@playwright/test";
import { openIncident, runToIncident, watchErrors } from "./helpers";

test("clicking a number opens its receipt with SQL and as_of; re-run behaves per mode", async ({ page, request }) => {
  const errors = watchErrors(page);
  await runToIncident(page, request);
  const sheet = await openIncident(page);

  const num = sheet.locator("button.num").first();
  await expect(num).toBeVisible();
  await expect(num).toHaveAttribute("title", "Open the query behind this number");
  const query = page.waitForResponse((response) => /^\/receipts\/r\d+$/.test(new URL(response.url()).pathname));
  await num.click();
  expect((await query).ok()).toBe(true);

  const drawer = page.getByRole("dialog", { name: "Evidence query" });
  await expect(drawer).toBeVisible();
  await expect(drawer.locator("pre.sql")).toContainText("SELECT");
  await expect(drawer.getByText("as_of (pinned)")).toBeVisible();
  await expect(drawer.locator(".facts")).toContainText(/\d\d:\d\d/);

  const source = await request.get("/health");
  expect(source.ok()).toBe(true);
  const rerun = drawer.getByRole("button", { name: "Re-run SQL" });
  if ((await source.json()).rerun) {
    await rerun.click();
    await expect(drawer.locator(".verify.ok")).toContainText("✓ Same hash", { timeout: 20_000 });
    await expect(drawer.locator(".verify.bad")).toHaveCount(0);
  } else {
    await expect(rerun).toHaveCount(0);
  }
  await page.keyboard.press("Escape");
  await expect(drawer).toBeHidden();
  expect(errors()).toEqual([]);
});
