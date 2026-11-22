import { expect, test } from "@playwright/test";
import { LIVE, replay, watchErrors } from "./helpers";

test("Since you were away opens as a workspace report", async ({ page, request }) => {
  const errors = watchErrors(page);
  if (!LIVE) await replay(request, { action: "end" });
  await page.goto("/?view=report&fxintro=0");
  const report = page.getByRole("region", { name: "morning report" });
  await expect(report.getByRole("heading", { name: "Since you were away" })).toBeVisible();
  await expect(report.locator(".mr-line").first()).toBeVisible();
  await expect(report.getByRole("button", { name: "Copy as Markdown" })).toBeEnabled();
  expect(errors()).toEqual([]);
});
