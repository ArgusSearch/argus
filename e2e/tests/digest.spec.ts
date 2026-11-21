import { expect, test } from "@playwright/test";
import { runToIncident, watchErrors } from "./helpers";

test("While you slept opens and shows lines", async ({ page, request }) => {
  const errors = watchErrors(page);
  await runToIncident(page, request);
  await page.locator(".header").getByRole("button", { name: "While you slept" }).click();
  const modal = page.getByRole("dialog", { name: "While you slept" });
  await expect(modal).toBeVisible();
  await expect(modal.locator(".dline").first()).toBeVisible({ timeout: 10_000 });
  expect(await modal.locator(".dline").count()).toBeGreaterThan(0);
  await expect(modal.getByRole("button", { name: "Copy as Markdown" })).toBeEnabled();
  await page.keyboard.press("Escape");
  await expect(modal).toBeHidden();
  expect(errors()).toEqual([]);
});
