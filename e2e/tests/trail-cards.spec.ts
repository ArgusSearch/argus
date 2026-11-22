import { expect, test } from "@playwright/test";
import { LIVE, incidentCard, openMissionControl, replay } from "./helpers";

// The investigation row is pinned to its newest step; every card it shows must be whole, never cut
// through its text at the panel edge (#16). Checked at the video size and at a laptop size.
for (const [width, height] of [
  [1920, 1080],
  [1440, 900],
]) {
  test(`trail cards are never cut at the edge at ${width}x${height}`, async ({ page, request }) => {
    test.skip(LIVE, "replay-only: drives the recorded S1 run");
    await page.setViewportSize({ width, height });
    await replay(request, { action: "restart", speed: 64 });
    await replay(request, { action: "play" });
    await openMissionControl(page);
    await expect(incidentCard(page)).toBeVisible({ timeout: 90_000 });
    await replay(request, { action: "pause" });
    await page.waitForTimeout(1200); // let the row finish its smooth scroll to the newest step
    const cut = await page.locator(".trail .trail-steps").evaluate((row) => {
      const box = row.getBoundingClientRect();
      return [...row.querySelectorAll(":scope > .tstep")]
        .map((card) => ({ n: card.querySelector(".tstep-n")?.textContent ?? "?", r: card.getBoundingClientRect() }))
        .filter(({ r }) => r.right > box.left + 1 && r.left < box.right - 1) // visible at all
        .filter(({ r }) => r.left < box.left - 1 || r.right > box.right + 1) // but not whole
        .map(({ n, r }) => `${n} [${Math.round(r.left)}..${Math.round(r.right)}] in [${Math.round(box.left)}..${Math.round(box.right)}]`);
    });
    expect(cut, "cards cut at the edge of the trail row").toEqual([]);
  });
}
