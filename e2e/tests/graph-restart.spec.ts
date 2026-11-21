import { expect, test } from "@playwright/test";
import { LIVE, openMissionControl, replay } from "./helpers";

// A replay restart refetches the graph while a burst of events is folded; the metric boxes must stay
// visible the whole time (React Flow hides nodes it has not measured yet).
test("the metric graph stays visible across a replay restart", async ({ page, request }) => {
  test.skip(LIVE, "restart is a replay control");
  // remove test.fail once the fix for #33 (PR #39) is on main
  test.fail(true, "graph goes blank after a restart: https://github.com/ArgusSearch/argus/issues/33");
  await replay(request, { action: "restart", speed: 64 });
  await replay(request, { action: "play" });
  await openMissionControl(page);
  const nodes = page.locator(".react-flow__node");
  await expect(nodes.first()).toBeVisible({ timeout: 15_000 });

  const hidden = () =>
    nodes.evaluateAll((els) => els.filter((e) => getComputedStyle(e).visibility === "hidden").length);
  for (let round = 0; round < 3; round++) {
    await replay(request, { action: "restart", speed: 64 });
    await replay(request, { action: "play" });
    // sample for 4 s after the restart: no moment where the boxes are hidden
    const samples: number[] = [];
    for (let i = 0; i < 20; i++) {
      samples.push(await hidden());
      await page.waitForTimeout(200);
    }
    expect(samples.filter((n) => n > 0).length, `samples with hidden nodes after restart ${round + 1}: ${samples.join(",")}`).toBe(0);
  }
});
