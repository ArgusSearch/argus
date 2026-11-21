import { expect, test } from "@playwright/test";
import { openMissionControl } from "./helpers";

// Every metric box shows its unit (COUNT, RATE, EUR) next to a sparkline: the text must not run under it.
test("unit labels on metric nodes are not overdrawn by the sparkline", async ({ page }) => {
  await page.setViewportSize({ width: 1920, height: 1080 });
  await openMissionControl(page);
  await expect(page.locator(".react-flow__node").first()).toBeVisible({ timeout: 15_000 });
  const overdrawn = await page.locator(".mnode-foot").evaluateAll((feet) =>
    feet
      .filter((foot) => {
        const kind = foot.querySelector(".mnode-kind");
        const spark = foot.querySelector("svg");
        if (!kind?.firstChild || !spark) return false;
        const range = document.createRange();
        range.selectNodeContents(kind);
        return range.getBoundingClientRect().right > spark.getBoundingClientRect().left + 0.5;
      })
      .map((foot) => foot.closest(".react-flow__node")?.getAttribute("data-id") ?? "?"),
  );
  expect(overdrawn, `nodes whose unit text runs under the sparkline: ${overdrawn.join(", ")}`).toEqual([]);
});
