import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type ConsoleMessage, type Locator, type Page } from "@playwright/test";
import { startApi, stopApi, type OwnApi } from "./own-api";

// The "Argus Ice" style layer (web/src/fx, `?fx=1|ice|night`), the look the demo video is recorded in.
// Since the IA redesign (fm/argus-ia-redesign, merged in e0ce93b) it is a workspace: a sidebar of named sections
// (Monitor: Overview, Incidents, Live investigation, While you slept; Explore: Visualization, Village, Metric tree;
// Proof: Track record, Glossary), an overview page in plain words, and one page per incident instead of the sheet.
// It runs on its own replay API (`argus api --replay fixtures`, S1), because demo mode restarts the replay at its
// own speed and the other tests drive play, pause and speed. Replay-only. Every wait is bounded.
// ARGUS_E2E_FX=0 skips the spec; ARGUS_E2E_FX_PORT moves its server (default 8014).
// With ARGUS_E2E_SHOTS=1 the last test saves docs/qa/screenshots/fx-*.png (1920x1080, the overview also 1440x900).
const PORT = Number(process.env.ARGUS_E2E_FX_PORT ?? 8014);
const SHOTS = Boolean(process.env.ARGUS_E2E_SHOTS);
/** the opening without the loader hold, so a test does not wait for the intro */
const FX = "/?fx=1&fxintro=0&entry=0";
/** the URL the 3-minute video is recorded in (web/src/fx/flag.ts) */
const RECORDING = "/?demo=1&captions=1&fx=1";
/** the plain label of SUPPORTED_CAUSE (web/src/fx/workspace/plain.ts VERDICT) */
const SUPPORTED = "Supported cause (evidenced)";
/** where S1's drop sits (DE / android / PayCo), as the workspace words it */
const WHERE = ["Germany", "Android", "PayCo"];

let api: OwnApi | null = null;
let base = "";

test.describe("Argus Ice (fx layer)", () => {
  test.skip(process.env.ARGUS_E2E_MODE === "live", "replay-only: runs on its own recorded S1 replay");
  test.skip(process.env.ARGUS_E2E_FX === "0", "ARGUS_E2E_FX=0");

  test.beforeAll(async () => {
    api = await startApi(PORT, ["--replay", "fixtures"]);
    base = api.base;
  });
  test.afterAll(async () => {
    await stopApi(api);
    api = null;
  });

  async function post(page: Page, body: object): Promise<void> {
    const res = await page.request.post(`${base}/replay`, { data: body });
    expect(res.status(), `POST /replay ${JSON.stringify(body)}`).toBeLessThan(300);
  }

  async function health(page: Page): Promise<{ stream: string; run: { speed: number; finished: boolean } }> {
    return (await page.request.get(`${base}/health`)).json();
  }

  /** Open an fx URL, wait for the loader to leave, check the theme attribute. */
  async function open(page: Page, path: string, theme: "ice" | "night" = "ice"): Promise<void> {
    await page.goto(base + path);
    await expect(page).toHaveTitle("Argus · Mission Control");
    await expect(page.locator("html")).toHaveAttribute("data-fx", theme);
    await expect(page.locator(".fx-loader")).toHaveCount(0, { timeout: 10_000 });
    await expect(page.locator("html")).toHaveAttribute("data-fx-phase", "ready", { timeout: 10_000 });
  }

  /**
   * Play S1 from the top at 64x and wait for INC-0001's verdict on the overview; the run is paused there. The
   * overview's 3D path preview under SwiftShader can keep the page some seconds behind the stream on a loaded
   * 8 GB Mac, hence 45 s.
   */
  async function runToVerdict(page: Page): Promise<void> {
    await post(page, { action: "restart", speed: 64 });
    await post(page, { action: "play" });
    await expect(task(page).getByText(SUPPORTED, { exact: true })).toBeVisible({ timeout: 45_000 });
    await post(page, { action: "pause" });
  }

  /** Play at 64x until the replay's clock reaches `until`, then continue at `speed`. */
  async function fastForward(page: Page, until: string, speed: number): Promise<void> {
    await post(page, { speed: 64 });
    await expect
      .poll(async () => ((await page.request.get(`${base}/health`)).json() as Promise<{ sim_ts: string }>).then((h) => h.sim_ts >= until), {
        timeout: 15_000,
        intervals: [50],
        message: `replay clock reaches ${until}`,
      })
      .toBe(true);
    await post(page, { speed });
  }

  const sidebar = (page: Page) => page.getByRole("navigation", { name: "sections" });
  const navButton = (page: Page, name: string) => sidebar(page).getByRole("button", { name: new RegExp(`^${name}`) });
  /** the workspace's start page (web/src/fx/workspace/Overview.tsx) */
  const overview = (page: Page) => page.getByRole("main", { name: "overview" });
  /** INC-0001 in the overview's "This week: your decisions" list */
  const task = (page: Page, id = "INC-0001") => overview(page).getByRole("listitem").filter({ hasText: id });
  /** the incident's own page (web/src/fx/workspace/IncidentPage.tsx), the redesign's incident report */
  const incidentPage = (page: Page, id = "INC-0001") => page.getByRole("main", { name: `incident ${id}` });
  const card = (scope: Locator, title: RegExp) => scope.locator("section").filter({ has: scope.page().getByRole("heading", { name: title }) });

  /** Every sidebar entry (web/src/fx/workspace/Workspace.tsx NAV) and the region it shows. */
  const SECTIONS = [
    { nav: "Overview", region: (p: Page) => overview(p) },
    { nav: "Incidents", region: (p: Page) => p.getByRole("main", { name: "incidents" }) },
    { nav: "Live investigation", region: (p: Page) => p.getByRole("region", { name: "investigation" }) },
    { nav: "While you slept", region: (p: Page) => p.getByRole("region", { name: "morning report" }) },
    { nav: "Visualization", region: (p: Page) => p.getByRole("complementary", { name: "what the map shows" }) },
    { nav: "Village", region: (p: Page) => p.getByRole("main", { name: "village" }) },
    { nav: "Metric tree", region: (p: Page) => p.getByRole("region", { name: "metric tree" }) },
    { nav: "Track record", region: (p: Page) => p.getByRole("region", { name: "bench scorecard" }) },
    { nav: "Glossary", region: (p: Page) => p.getByRole("main", { name: "glossary" }) },
  ];

  test("?fx=1 loads Argus Ice: theme set, loader gone, the overview's KPI tiles and one key metric per north-star metric, no errors", async ({ page }) => {
    const errors = watchFxErrors(page);
    await open(page, FX);
    await expect(navButton(page, "Overview")).toHaveAttribute("aria-current", "page");
    await expect(overview(page).getByRole("heading", { level: 1 })).toBeVisible();

    const graph = (await (await page.request.get(`${base}/graph`)).json()) as { nodes: { id: string; north_star?: boolean }[] };
    const stars = graph.nodes.filter((n) => n.north_star);
    expect(stars.length, "the graph has north-star metrics").toBeGreaterThan(0);
    // the five KPI tiles (web/src/fx/workspace/health.ts tiles), in plain words
    const tiles = overview(page).getByRole("region", { name: "key figures" });
    await expect(tiles).toBeVisible();
    for (const label of ["Cost of incidents", "Open incidents", "Key metrics normal", "Small moves ignored", "Human actions"]) {
      // not exact: a tile label with a glossary term carries its tooltip text
      await expect(tiles.getByText(label), label).toBeVisible();
    }
    await expect(tiles).toContainText(`of ${stars.length}`); // "Key metrics normal: 7 of 7"
    // the shop health gauge and one row per north-star metric in "Key metrics, this hour"
    await expect(overview(page).getByRole("img", { name: /^Shop health \d+ of 100$/ })).toBeVisible();
    const metrics = card(overview(page), /Key metrics, this hour/).getByRole("button");
    await expect(metrics).toHaveCount(stars.length);
    for (const m of await metrics.all()) await expect(m).toHaveAttribute("title", /: how unusual /);
    noErrors(errors());
  });

  test("S1 at 64x: INC-0001 is a supported cause in Germany / Android / PayCo on the overview and in Incidents; its report page opens and Escape goes back", async ({ page }) => {
    const errors = watchFxErrors(page);
    await open(page, FX);
    await runToVerdict(page);

    const row = task(page);
    await expect(row).toHaveCount(1);
    await expect(row.getByText(SUPPORTED, { exact: true })).toBeVisible();
    for (const s of WHERE) await expect(row).toContainText(s);
    await expect(row).not.toContainText("SUPPORTED_CAUSE");

    // the incident's report is its own page since the redesign (it was a sheet over the graph)
    await row.getByRole("button", { name: "See why" }).click();
    const report = incidentPage(page);
    await expect(report).toBeVisible();
    await expect(navButton(page, "Incidents")).toHaveAttribute("aria-current", "page");
    await expect(report.getByRole("heading", { name: "What happened" })).toBeVisible();
    await expect(report.getByText(SUPPORTED, { exact: true }).first()).toBeVisible();
    await expect(report.getByRole("heading", { level: 1 })).toContainText("PayCo");
    for (const s of WHERE) await expect(report.getByRole("heading", { level: 1 })).toContainText(s);
    await expect(report.getByRole("button", { name: "Copy report" })).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(report).toBeHidden();
    await expect(navButton(page, "Overview")).toHaveAttribute("aria-current", "page");

    // the incident list has the same verdict and place; its badge counts nothing open once S1 resolved
    await navButton(page, "Incidents").click();
    const listed = page.getByRole("main", { name: "incidents" }).getByRole("row").filter({ hasText: "INC-0001" });
    await expect(listed).toHaveCount(1);
    await expect(listed.getByText(SUPPORTED, { exact: true })).toBeVisible();
    for (const s of WHERE) await expect(listed).toContainText(s);
    await listed.getByRole("button", { name: "Open" }).click();
    await expect(incidentPage(page)).toBeVisible();
    await page.keyboard.press("Escape");
    await expect(page.getByRole("main", { name: "incidents" })).toBeVisible();
    noErrors(errors());
  });

  test("every sidebar section opens by click, and the view keys 1-5 switch sections", async ({ page }) => {
    const errors = watchFxErrors(page);
    await open(page, FX);
    for (const s of SECTIONS) {
      await navButton(page, s.nav).click();
      await expect(navButton(page, s.nav)).toHaveAttribute("aria-current", "page");
      await expect(s.region(page)).toBeVisible();
      await expect(sidebar(page).locator("[aria-current=page]")).toHaveCount(1);
    }
    // the view host's own shortcuts (web/src/views/index.tsx), followed by the sidebar (web/src/fx/nav.ts).
    // Start from Track record so that "1" is a change of the host's tab (see the key-1 test below).
    await navButton(page, "Track record").click();
    // key 1 is covered by the #63 test below: since 3b71e6d it does not switch to the visualization even from Track record
    const KEYS: [string, string][] = [
      ["2", "Metric tree"],
      ["3", "Live investigation"],
      ["4", "While you slept"],
      ["5", "Track record"],
    ];
    for (const [key, nav] of KEYS) {
      await page.keyboard.press(key);
      await expect(navButton(page, nav), `key ${key}`).toHaveAttribute("aria-current", "page");
      await expect(SECTIONS.find((s) => s.nav === nav)!.region(page)).toBeVisible();
    }
    await navButton(page, "Overview").click();
    await expect(overview(page)).toBeVisible();
    noErrors(errors());
  });

  test("key 1 on the overview opens the visualization (#63)", async ({ page }) => {
    // The overview (like every workspace page: Incidents, Glossary, Village) sits on the view host's "graph" tab,
    // so "1" changes no aria-selected and watchHost (web/src/fx/nav.ts) never hears it: the overview stays.
    // Still so after the IA redesign (e0ce93b). Remove this line once #63 is fixed.
    test.fail(true, "#63: key 1 does nothing on the overview: the host tab is already 'graph' (web/src/fx/nav.ts watchHost)");
    await open(page, FX);
    await expect(navButton(page, "Overview")).toHaveAttribute("aria-current", "page");
    await page.keyboard.press("1");
    await expect(navButton(page, "Visualization")).toHaveAttribute("aria-current", "page", { timeout: 2_000 });
  });

  test("the visualization renders the 3D scene (canvas) or, without WebGL2, the classic graph, with the panel that explains it", async ({ page }) => {
    const errors = watchFxErrors(page);
    await open(page, FX);
    await navButton(page, "Visualization").click();
    await expect(navButton(page, "Visualization")).toHaveAttribute("aria-current", "page");
    await expect(page.getByRole("region", { name: "metric graph" })).toBeVisible();
    await expect(page.getByRole("complementary", { name: "what the map shows" })).toBeVisible();
    const scene = page.locator('[data-fx-scene="full"]');
    const classic = page.locator(".react-flow__node");
    await expect(scene.or(classic).first()).toBeAttached({ timeout: 10_000 });
    const webgl2 = await page.evaluate(() => document.createElement("canvas").getContext("webgl2") !== null);
    if (await scene.count()) {
      test.info().annotations.push({ type: "graph", description: `3D scene (webgl2=${webgl2})` });
      const canvas = page.locator("#fx-stage canvas.fxs-canvas");
      await expect(canvas).toBeVisible();
      const box = await canvas.boundingBox();
      expect(box && box.width > 300 && box.height > 200, `canvas size ${JSON.stringify(box)}`).toBeTruthy();
      await expect(classic).toHaveCount(0);
    } else {
      test.info().annotations.push({ type: "graph", description: `classic graph (webgl2=${webgl2})` });
      await expect(classic.first()).toBeVisible({ timeout: 10_000 });
    }
    noErrors(errors());
  });

  test("the village opens from the sidebar, renders its seven agents on a stage and plays, no errors", async ({ page }) => {
    // lane G's view (web/src/village, fm/argus-lane-g): the sidebar shows "Village" when Village.tsx exists;
    // `?view=village` deep-links to it. It plays a recorded tape (S4 by default) in the browser.
    const errors = watchFxErrors(page);
    await open(page, FX);
    await navButton(page, "Village").click();
    await expect(navButton(page, "Village")).toHaveAttribute("aria-current", "page");
    const village = page.getByRole("region", { name: "Argus village" });
    await expect(village).toBeVisible({ timeout: 15_000 }); // a lazy chunk with three.js
    await expect(village.getByRole("heading", { level: 1 })).toHaveText("Seven agents, one igloo each");
    for (const agent of ["B.E.A.C.O.N.", "G.R.I.D.", "S.L.E.U.T.H.", "T.I.C.K.E.R.", "D.O.U.B.T.", "S.C.R.I.B.E.", "L.E.V.E.R."]) {
      await expect(village.getByRole("button", { name: new RegExp(`^${agent.replace(/\./g, "\\.")}`) }), agent).toBeAttached();
    }
    // the village starts on live data since 9b60547; pick the recorded S4 tape (not "S4 agent")
    const s4 = village.getByRole("navigation", { name: "source" }).getByRole("button", { name: "S4", exact: true });
    await s4.click();
    await expect(s4).toHaveAttribute("aria-pressed", "true");
    // the stage: the three.js canvas, or the 2D stage without WebGL
    const canvas = village.locator("canvas.vl-canvas");
    if (await canvas.count()) {
      await expect(canvas).toBeVisible();
      const box = await canvas.boundingBox();
      expect(box && box.width > 300 && box.height > 200, `village canvas size ${JSON.stringify(box)}`).toBeTruthy();
      test.info().annotations.push({ type: "village", description: "3D stage" });
    } else {
      await expect(village.getByRole("button", { name: /igloo$/ }).first()).toBeVisible();
      test.info().annotations.push({ type: "village", description: "2D stage" });
    }
    // the tape plays by itself: the step counter moves
    const progress = village.getByText(/^step \d+ of \d+/);
    await expect(progress).toBeVisible();
    const first = await progress.textContent();
    await expect(progress, "the village tape advances").not.toHaveText(first ?? "", { timeout: 15_000 });
    noErrors(errors());
  });

  test("?fx=night sets data-fx=night", async ({ page }) => {
    const errors = watchFxErrors(page);
    await open(page, "/?fx=night&fxintro=0&entry=0", "night");
    await expect(overview(page)).toBeVisible();
    noErrors(errors());
  });

  test("the recording URL plays hands-off: captions, investigation, the report opens and closes by itself", async ({ page }) => {
    test.setTimeout(60_000);
    const errors = watchFxErrors(page);
    const before = (await health(page)).stream;
    // the recording URL as is, intro included
    await page.goto(base + RECORDING);
    const html = page.locator("html");
    await expect(html).toHaveAttribute("data-fx", "ice");
    await expect(html).toHaveClass(/\bargus-demo\b/);
    await expect(html).toHaveAttribute("data-demo", "");
    // one caption line from the start (beat "watching"); demo mode hides the replay controls
    const caption = page.getByRole("status").locator(".cap-line");
    await expect(caption).toHaveText(/^Watching \d+ metrics each simulated hour\. No one is at the keyboard\.$/);
    await expect(page.locator(".controls")).toBeHidden();
    await expect(page.locator(".fx-loader")).toHaveCount(0, { timeout: 10_000 });
    await expect(navButton(page, "Overview")).toHaveAttribute("aria-current", "page");

    // demo mode restarted the replay itself at its default speed 2 (web/src/views/demo/demo.ts)
    await expect.poll(async () => (await health(page)).stream, { timeout: 10_000, message: "demo mode restarts the replay" }).not.toBe(before);
    expect((await health(page)).run.speed).toBe(2);
    // fast-forward the quiet hours to the morning of the anomaly (Sat 21 Nov 20:00); the page is not touched.
    // Then 4x: the walk stays readable, and the rest of the run (30 h, then the 8 s loop linger) outlasts
    // the report hold (3.5 s + 12 s), so the loop does not restart the choreography under the test.
    await fastForward(page, "2026-11-21T12:00:00", 4);

    // the first step switches to the live investigation by itself, the captions follow the walk
    await expect(navButton(page, "Live investigation")).toHaveAttribute("aria-current", "page", { timeout: 15_000 });
    await expect(page.getByRole("region", { name: "investigation" })).toBeVisible();
    await expect(caption).toHaveClass(/b-(checks|localised|suspects|verdict|monitoring)/);
    // demo.ts: `Verdict for <where>: <verdict>. ...`
    await expect(caption).toHaveText(/Verdict for .*PayCo.*: supported cause/i, { timeout: 15_000 });

    // 3.5 s after the verdict the incident page opens (the redesign's report); it closes by itself and the
    // page goes back to the overview
    const report = incidentPage(page);
    await expect(report).toBeVisible({ timeout: 8_000 });
    const opened = Date.now();
    await expect(report.getByText(SUPPORTED, { exact: true }).first()).toBeVisible();
    await expect(report.getByRole("heading", { level: 1 })).toContainText("PayCo");
    await expect(page.getByRole("status").locator(".cap-line")).toBeVisible();
    await expect(report).toBeHidden({ timeout: 16_000 });
    // `hold` is 12 s; on main e0ce93b the page leaves after about 8 s (see e2e/README.md, "the demo report hold")
    const held = `${((Date.now() - opened) / 1000).toFixed(1)} s (hold 12 s)`;
    test.info().annotations.push({ type: "report open for", description: held });
    console.log(`the demo report stayed open ${held}`);
    await expect(navButton(page, "Overview")).toHaveAttribute("aria-current", "page", { timeout: 3_000 });
    await expect(overview(page)).toBeVisible();
    await expect(page.locator("html")).toHaveClass(/\bargus-demo\b/);
    noErrors(errors());
  });

  test("QA screenshots of the fx layer (ARGUS_E2E_SHOTS=1)", async ({ page }) => {
    test.skip(!SHOTS, "set ARGUS_E2E_SHOTS=1 to capture the fx screenshots");
    test.setTimeout(180_000);
    const out = resolve(process.cwd(), "../docs/qa/screenshots");
    mkdirSync(out, { recursive: true });
    const BIG = { width: 1920, height: 1080 };
    const SMALL = { width: 1440, height: 900 };
    const shot = async (name: string) => {
      // the 3D scene and the path preview materialize over about 2 s after a load, a resize or a new subject
      await page.waitForTimeout(3000);
      await page.screenshot({ path: `${out}/fx-${name}.png` });
    };
    const both = async (name: string) => {
      await shot(`${name}-1920`);
      await page.setViewportSize(SMALL);
      await shot(`${name}-1440`);
      await page.setViewportSize(BIG);
    };
    await page.setViewportSize(BIG);
    await open(page, FX);

    // 1. mid-run: the investigation is walking, no verdict yet (64x to the evening of Sat 21 Nov, then 1x)
    await post(page, { action: "restart", speed: 64 });
    await post(page, { action: "play" });
    await fastForward(page, "2026-11-21T16:00:00", 1);
    await expect(sidebar(page).getByLabel("investigation running")).toBeVisible({ timeout: 30_000 });
    await post(page, { action: "pause" });
    await both("dashboard-midrun");
    await navButton(page, "Live investigation").click();
    await shot("investigation-midrun-1920");
    await navButton(page, "Overview").click();

    // 2. INC-0001 explained, before it starts to recover (still 1x, paused on the verdict)
    await post(page, { action: "play" });
    await expect(task(page).getByText(SUPPORTED, { exact: true })).toBeVisible({ timeout: 30_000 });
    await post(page, { action: "pause" });
    await both("dashboard-explained");

    // 3. the incident report, its own page
    await task(page).getByRole("button", { name: "See why" }).click();
    await expect(incidentPage(page).getByRole("heading", { name: "What happened" })).toBeVisible();
    await shot("incident-report-1920");
    await page.keyboard.press("Escape");
    await expect(incidentPage(page)).toBeHidden();

    // 4. the visualization
    await navButton(page, "Visualization").click();
    await shot("graph-1920");

    // 5. the village
    await navButton(page, "Village").click();
    await expect(page.getByRole("region", { name: "Argus village" })).toBeVisible({ timeout: 15_000 });
    await shot("village-1920");

    // 6. the night theme, same paused state
    await open(page, "/?fx=night&fxintro=0&entry=0", "night");
    // the night preview materializes slower under SwiftShader (about 4 s)
    await page.waitForTimeout(3000);
    await shot("night-1920");

    // 7. the recording URL with captions mid-play (the investigation walking at 1x)
    const before = (await health(page)).stream;
    await page.goto(base + RECORDING);
    await expect.poll(async () => (await health(page)).stream, { timeout: 10_000 }).not.toBe(before);
    await fastForward(page, "2026-11-21T16:00:00", 1);
    await expect(navButton(page, "Live investigation")).toHaveAttribute("aria-current", "page", { timeout: 15_000 });
    await expect(page.getByRole("status").locator(".cap-line")).toHaveClass(/b-(localised|suspects)/, { timeout: 20_000 });
    await shot("demo-captions-1920");
  });
});

/** The page error of a view transition that a newer page change skipped (see noErrors). */
const SKIPPED_TRANSITION = /Transition was skipped/;

/**
 * No console errors, page errors or failed requests. One known app bug is told apart: web/src/fx/nav.ts `transition()`
 * catches only the `finished` promise of `document.startViewTransition`, so when a page change starts while the previous
 * one still runs (quick sidebar clicks, demo mode's own switches) the skipped transition's `ready` promise rejects
 * unhandled: "pageerror: Transition was skipped. New ViewTransition started". It depends on timing, so the test marks
 * itself as an expected failure only when it hits it (after every other check passed); remove that once nav.ts handles it.
 */
function noErrors(errors: string[]): void {
  expect(errors.filter((e) => !SKIPPED_TRANSITION.test(e)), "errors other than a skipped view transition").toEqual([]);
  const skipped = errors.filter((e) => SKIPPED_TRANSITION.test(e));
  test.fail(skipped.length > 0, `a skipped view transition rejected unhandled ${skipped.length}x: web/src/fx/nav.ts transition() catches only .finished, not .ready`);
  expect(skipped, "unhandled rejections of skipped view transitions").toEqual([]);
}

/** Console errors, page errors and failed requests, except the documented 501 stubs and the replay's 409s. */
function watchFxErrors(page: Page): () => string[] {
  const errors: string[] = [];
  const allowed = (status: number) => status === 501 || status === 409;
  page.on("console", (msg: ConsoleMessage) => {
    if (msg.type() !== "error") return;
    // Chromium logs every failed resource as a console error; the response handler below judges those
    const failed = /Failed to load resource: the server responded with a status of (\d+)/.exec(msg.text());
    if (failed && allowed(Number(failed[1]))) return;
    errors.push(`console: ${msg.text()}`);
  });
  page.on("pageerror", (err) => errors.push(`pageerror: ${err.message}`));
  page.on("requestfailed", (req) => {
    // the SSE stream is cut when the page navigates or the test ends
    if (new URL(req.url()).pathname === "/events") return; // also /events?include_stream=true (the reconnecting client)
    errors.push(`failed: ${req.method()} ${req.url()} ${req.failure()?.errorText ?? ""}`);
  });
  page.on("response", (res) => {
    if (res.status() >= 400 && !allowed(res.status())) errors.push(`http ${res.status()}: ${res.request().method()} ${res.url()}`);
  });
  return () => errors;
}
