import { expect, test } from "@playwright/test";

test("the metric placement toolbar is available only in Visualization", async ({ page }) => {
  await page.goto("/?fx=night&fxintro=0&entry=0");
  const sidebar = page.getByRole("navigation", { name: "sections" });
  const toolbar = page.locator('.gx-bar[aria-label="new metrics"]');

  await expect(toolbar).toBeAttached();
  await expect(toolbar).toBeHidden();
  await sidebar.getByRole("button", { name: "Visualization" }).click();
  await expect(toolbar).toBeVisible();
  await sidebar.getByRole("button", { name: "Metric tree" }).click();
  await expect(toolbar).toBeHidden();
});
