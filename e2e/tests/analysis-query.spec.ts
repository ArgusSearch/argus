import { expect, test } from "@playwright/test";

test("the Analysis query labels and identifies each field", async ({ page }) => {
  await page.goto("/?fx=night&fxintro=0&view=dashboard&analysis=overview");
  const query = page.getByRole("region", { name: "Analysis query" });
  await expect(query).toBeVisible({ timeout: 30_000 });

  await expect(query.getByRole("combobox", { name: "Metric" })).toHaveAttribute("name", "metric");
  await expect(query.getByRole("combobox", { name: "Segment" })).toHaveAttribute("name", "segment");
  const period = query.getByRole("combobox", { name: "Period" });
  await expect(period).toHaveAttribute("name", "period");
  await period.selectOption("24h");
  await expect(page).toHaveURL(/[?&]period=24h(?:&|$)/);
});
