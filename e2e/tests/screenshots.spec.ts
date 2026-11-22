import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test } from "@playwright/test";
import { health, incidentCard, openIncident, openMissionControl, replay } from "./helpers";

// Screenshots for the QA doc, not a check. Off by default; run with
//   ARGUS_E2E_SHOTS=1 npm --prefix e2e test -- screenshots
// PNGs land in docs/qa/screenshots/<viewport>-<n>-<state>.png (replay mode only).
const OUT = resolve(process.cwd(), "../docs/qa/screenshots");
const VIEWPORTS = [
  { width: 1920, height: 1080 },
  { width: 1440, height: 900 },
];

for (const viewport of VIEWPORTS) {
  test.describe(`${viewport.width}x${viewport.height}`, () => {
    test.use({ viewport });

    test(`replay page states at ${viewport.width}x${viewport.height}`, async ({ page, request }) => {
      test.skip(!process.env.ARGUS_E2E_SHOTS, "set ARGUS_E2E_SHOTS=1 to capture the QA screenshots");
      test.skip(process.env.ARGUS_E2E_MODE === "live", "the screenshots are taken from the recorded replay");
      mkdirSync(OUT, { recursive: true });
      const shot = (n: number, name: string) =>
        page.screenshot({ path: `${OUT}/${viewport.width}x${viewport.height}-${n}-${name}.png`, animations: "disabled" });

      await replay(request, { action: "restart", speed: 8 });
      await replay(request, { action: "play" });
      await openMissionControl(page);

      // 1. mid-run: the first anomaly is on the board and being checked, no verdict yet. At 8x the verdict
      // lands about a second after the alarm, so slow to 1x a few hours before it (clock 20:00 on Sat 21 Nov)
      // and shoot on the alarm: at 1x the walk through the playbook takes about 12 s.
      await expect(page.locator(".clock-time")).toHaveText(/Sat 21 Nov · 1[5-9]:/, { timeout: 90_000 });
      await replay(request, { speed: 1 });
      await expect(page.locator(".funnel-step.alarm").first()).toBeVisible({ timeout: 90_000 });
      await expect(incidentCard(page).locator(".pill.SUPPORTED_CAUSE")).toHaveCount(0);
      await shot(1, "mid-run");
      await replay(request, { speed: 8 });

      // 2. The incident is explained (the toast announces it).
      const card = incidentCard(page);
      await expect(card.locator(".pill.SUPPORTED_CAUSE")).toBeVisible({ timeout: 90_000 });
      await expect(page.getByRole("status").filter({ hasText: "Incident explained" })).toBeVisible();
      await shot(2, "inc-0001-explained");

      // 3. the incident sheet
      const sheet = await openIncident(page);
      await page.waitForTimeout(800);
      await shot(3, "incident-sheet");

      // 4. a receipt drawer over the sheet
      const num = sheet.locator("button.num").first();
      await num.click();
      const drawer = page.getByRole("dialog", { name: "Evidence query" });
      await expect(drawer.locator("pre.sql")).toContainText("SELECT");
      await page.waitForTimeout(500);
      await shot(4, "receipt-drawer");
      await page.keyboard.press("Escape");
      await expect(drawer).toBeHidden();
      await page.keyboard.press("Escape");
      await expect(sheet).toBeHidden();

      // 5. The report once the run is over.
      await replay(request, { speed: 64 });
      await expect.poll(async () => (await health(request)).run.finished, { timeout: 90_000 }).toBe(true);
      await page.waitForTimeout(1000);
      await page.goto("/?view=report&fxintro=0");
      const report = page.getByRole("region", { name: "morning report" });
      await expect(report.locator(".mr-line").first()).toBeVisible({ timeout: 10_000 });
      await page.waitForTimeout(500);
      await shot(5, "since-you-were-away");
    });
  });
}
