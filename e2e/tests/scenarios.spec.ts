import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Page } from "@playwright/test";
import { incidentCard, watchErrors } from "./helpers";
import { startApi, stopApi, type OwnApi } from "./own-api";

// Every recorded scenario, replayed through its own API (`argus api --replay fixtures[/<scenario>]`, what
// `make api SCENARIO=<s>` runs) at 64x, and the outcome a judge reads off the page once the run is over.
// The truth per scenario is in fixtures/README.md and docs/qa. Replay-only: live mode has one world.
// ARGUS_E2E_SCENARIOS=0 skips the spec (about 40 s); ARGUS_E2E_SCENARIO_PORT moves its server (default 8013).
// With ARGUS_E2E_SHOTS=1 each test also saves the finished page at 1920x1080 to docs/qa/screenshots/scenario-<s>.png.
const PORT = Number(process.env.ARGUS_E2E_SCENARIO_PORT ?? 8013);

async function shot(page: Page, name: string): Promise<void> {
  if (!process.env.ARGUS_E2E_SHOTS) return;
  const out = resolve(process.cwd(), "../docs/qa/screenshots");
  mkdirSync(out, { recursive: true });
  // best effort: wait out the blank-graph spell after the reset so the picture shows the graph
  await page.locator(".react-flow__node").first().waitFor({ state: "visible", timeout: 20_000 }).catch(() => undefined);
  await page.waitForTimeout(800);
  await page.screenshot({ path: `${out}/scenario-${name}.png`, animations: "disabled" });
}

let api: OwnApi | null = null;
test.afterEach(async () => {
  await stopApi(api);
  api = null;
});

/** Start the scenario's replay API, open the page on it, play the run at 64x from the top and wait for its end. */
async function playScenario(page: Page, replayDir: string): Promise<string> {
  api = await startApi(PORT, ["--replay", replayDir]);
  const base = api.base;
  await page.goto(base);
  await expect(page).toHaveTitle("Argus · Mission Control");
  await expect(page.locator(".header .mode")).toHaveText("Replay · recorded run", { timeout: 10_000 });

  const post = async (body: object) => {
    const res = await page.request.post(`${base}/replay`, { data: body });
    expect(res.status(), `POST /replay ${JSON.stringify(body)}`).toBeLessThan(300);
  };
  await post({ action: "restart", speed: 64 });
  await post({ action: "play" });
  await expect
    .poll(async () => ((await (await page.request.get(`${base}/health`)).json()) as { run: { finished: boolean } }).run.finished, {
      timeout: 60_000,
      message: "run.finished",
    })
    .toBe(true);

  // give the page a moment to fold the tail of the stream; the graph is mounted and the feed is on screen.
  // Only "attached" for the graph: after a stream reset React Flow can keep every node visibility:hidden
  // for several seconds (reported, not this spec's subject), so "visible" would make this spec flaky.
  await page.waitForTimeout(1000);
  await expect(page.locator(".react-flow__node").first()).toBeAttached();
  await expect(page.locator(".feed article").first()).toBeVisible();
  return base;
}

const tabCount = (page: Page, label: string) =>
  page.locator(".tabs .tab", { hasText: label }).locator(".count");

test.describe("recorded scenarios at 64x", () => {
  test.skip(process.env.ARGUS_E2E_MODE === "live", "replay-only: each scenario is its own recorded run");
  test.skip(process.env.ARGUS_E2E_SCENARIOS === "0", "ARGUS_E2E_SCENARIOS=0");
  test.setTimeout(100_000);
  // the screenshots are for the demo video, so they are taken at 1920x1080 from the start
  if (process.env.ARGUS_E2E_SHOTS) test.use({ viewport: { width: 1920, height: 1080 } });

  test("S1: one incident, SUPPORTED CAUSE in DE / android / PayCo", async ({ page }) => {
    const errors = watchErrors(page);
    await playScenario(page, "fixtures");
    const card = incidentCard(page);
    await expect(card).toHaveCount(1);
    await expect(card.locator(".pill.SUPPORTED_CAUSE")).toHaveText("SUPPORTED CAUSE");
    for (const s of ["DE", "android", "PayCo"]) await expect(card.locator(".segs")).toContainText(s);
    await expect(tabCount(page, "Incidents")).toHaveText("1");
    await shot(page, "s1");
    expect(errors()).toEqual([]);
  });

  test("quiet: nothing injected, no incident card", async ({ page }) => {
    const errors = watchErrors(page);
    await playScenario(page, "fixtures/quiet");
    await expect(page.locator("article.card.incident")).toHaveCount(0);
    await expect(tabCount(page, "Incidents")).toHaveText("0");
    // not vacuous: the run did reach the page (the first edge tests are on the feed)
    await expect(page.locator(".feed article", { hasText: "Graph change" }).first()).toBeVisible();
    await shot(page, "quiet");
    expect(errors()).toEqual([]);
  });

  test("S2: planned FR ad-spend change, no incident card, a \"Didn't wake you\" note citing the plan", async ({ page }) => {
    const errors = watchErrors(page);
    await playScenario(page, "fixtures/s2");
    await expect(page.locator("article.card.incident")).toHaveCount(0);
    await expect(tabCount(page, "Incidents")).toHaveText("0");
    expect(Number(await tabCount(page, "Didn't wake you").innerText())).toBeGreaterThan(0);
    const note = page.locator("article.card.note-expected");
    await expect(note.first().locator(".card-kind")).toHaveText("Didn't wake you");
    // the note cites the plan it matched (a budget line or a calendar push, depending on the recording)
    await expect(note.first()).toContainText(/planned|budget/i);
    await shot(page, "s2");
    expect(errors()).toEqual([]);
  });

  test("S3: orders loader stall, no business incident, a \"Data issue · held back\" note", async ({ page }) => {
    const errors = watchErrors(page);
    await playScenario(page, "fixtures/s3");
    await expect(page.locator("article.card.incident")).toHaveCount(0);
    await expect(tabCount(page, "Incidents")).toHaveText("0");
    const note = page.locator("article.card.note-data_issue");
    await expect(note.first().locator(".card-kind")).toHaveText("Data issue · held back");
    await shot(page, "s3");
    expect(errors()).toEqual([]);
  });

  test("S4: ad-pacer overburn, SUPPORTED CAUSE on pacing in DE or FR", async ({ page }) => {
    const errors = watchErrors(page);
    await playScenario(page, "fixtures/s4");
    const card = incidentCard(page);
    await expect(card).toHaveCount(1);
    await expect(card.locator(".pill.SUPPORTED_CAUSE")).toHaveText("SUPPORTED CAUSE");
    const segs = card.locator(".segs");
    const text = `${await card.locator(".card-title").innerText()} ${(await segs.count()) ? await segs.innerText() : ""}`;
    expect(text, "title or segment names pacing").toMatch(/pacing/i);
    expect(text, "title or segment names DE or FR").toMatch(/\b(DE|FR)\b/);
    await shot(page, "s4");
    expect(errors()).toEqual([]);
  });

  test("S5: market-wide dip is expected (three notes), the PayCo routing fault is a SUPPORTED CAUSE", async ({ page }) => {
    const errors = watchErrors(page);
    await playScenario(page, "fixtures/s5");
    // the dip follows the independent market demand index: no page, one "didn't wake you" note per metric
    const notes = page.locator("article.card.note-expected");
    await expect(notes).toHaveCount(3);
    await expect(notes.filter({ hasText: /market/i })).toHaveCount(3);
    // the real fault inside the dip is still found
    const card = incidentCard(page);
    await expect(card).toHaveCount(1);
    await expect(card.locator(".pill.SUPPORTED_CAUSE")).toHaveText("SUPPORTED CAUSE");
    for (const s of ["DE", "android", "PayCo"]) await expect(card.locator(".segs")).toContainText(s);
    await expect(card.locator(".pill.state-resolved")).toBeVisible();
    await shot(page, "s5");
    expect(errors()).toEqual([]);
  });
});
