import { expect, test } from "@playwright/test";
import { LIVE, openMissionControl, watchErrors } from "./helpers";

test("the page loads with the header, the seed graph and no errors", async ({ page, request }) => {
  const errors = watchErrors(page);
  await openMissionControl(page);
  if (LIVE) await expect(page.locator(".header .mode")).toContainText(/^Live/);
  else await expect(page.locator(".header .mode")).toHaveText("Replay · recorded run");

  const graph = (await (await request.get("/graph")).json()) as { nodes: unknown[]; edges: unknown[]; logs: unknown[] };
  expect(graph.nodes.length).toBeGreaterThanOrEqual(27);
  await expect(page.locator(".graph-bar .sub")).toContainText(`${graph.nodes.length} metrics`);
  // one box per metric plus one per evidence log
  await expect(page.locator(".react-flow__node")).toHaveCount(graph.nodes.length + graph.logs.length);
  await expect(page.locator(".react-flow__edge").first()).toBeAttached();

  // the clock moves once the first tick arrives
  await expect(page.locator(".clock-time")).not.toHaveText("waiting for the first tick", { timeout: 15_000 });
  await page.waitForTimeout(1500);
  expect(errors()).toEqual([]);
});
