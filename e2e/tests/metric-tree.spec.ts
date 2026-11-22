import { expect, test } from "@playwright/test";

test("metric search keeps branch controls working and preserves the unfiltered tree", async ({ page }) => {
  await page.goto("/?classic=1&view=tree");
  const tree = page.getByRole("region", { name: "metric tree" });
  const search = tree.getByRole("textbox", { name: "Find a metric" });
  const collapseAll = tree.locator(".vw-bar").getByRole("button", { name: "Collapse", exact: true });
  const expandAll = tree.getByRole("button", { name: "Expand all" });
  const revenueToggle = tree.locator('[data-node="gmv"] > .tv-toggle');
  const paymentMetric = tree.locator('[data-node="payment_success_rate"]');

  await collapseAll.click();
  await expect(revenueToggle).toHaveAccessibleName("Expand");

  await search.fill("payment success");
  await expect(paymentMetric).toBeVisible();
  await revenueToggle.click();
  await expect(revenueToggle).toHaveAccessibleName("Expand");
  await expect(paymentMetric).toHaveCount(0);

  await revenueToggle.click();
  await expect(paymentMetric).toBeVisible();
  await collapseAll.click();
  await expect(paymentMetric).toHaveCount(0);
  await expandAll.click();
  await expect(paymentMetric).toBeVisible();

  await search.fill("nonexistent test metric");
  await expect(tree.getByRole("status")).toHaveText("No matches found.");
  await search.clear();
  await expect(revenueToggle).toHaveAccessibleName("Expand");
});
