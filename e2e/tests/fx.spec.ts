import { mkdirSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type ConsoleMessage, type Page } from "@playwright/test";
import { incidentCard } from "./helpers";
import { startApi, stopApi, type OwnApi } from "./own-api";

// The "Argus Ice" style layer (web/src/fx, `?fx=1|ice|night`), the look the demo video is recorded in.
// It runs on its own replay API (`argus api --replay fixtures`, S1), because demo mode restarts the replay at its
// own speed and the other tests drive play, pause and speed. Replay-only. Every wait is bounded.
// ARGUS_E2E_FX=0 skips the spec; ARGUS_E2E_FX_PORT moves its server (default 8014).
// With ARGUS_E2E_SHOTS=1 the last test saves docs/qa/screenshots/fx-*.png (1920x1080, the dashboard also 1440x900).
const PORT = Number(process.env.ARGUS_E2E_FX_PORT ?? 8014);
const SHOTS = Boolean(process.env.ARGUS_E2E_SHOTS);
/** the opening without the loader hold, so a test does not wait for the intro */
const FX = "/?fx=1&fxintro=0";
/** the URL the 3-minute video is recorded in (web/src/fx/flag.ts) */
const RECORDING = "/?demo=1&captions=1&fx=1";

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

  /** Play S1 from the top at 64x and wait for INC-0001's verdict on the dashboard; the run is paused there. */
  async function runToVerdict(page: Page): Promise<void> {
    await post(page, { action: "restart", speed: 64 });
    await post(page, { action: "play" });
    await expect(dashboard(page).locator(".fx-incident").filter({ hasText: "INC-0001" }).locator(".pill.SUPPORTED_CAUSE")).toBeVisible({ timeout: 20_000 });
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
  const dashboard = (page: Page) => page.getByRole("main", { name: "dashboard" });

  /** The region each sidebar section shows; the graph's is the classic panel or the 3D mount. */
  const SECTIONS = [
    { nav: "Dashboard", region: (p: Page) => dashboard(p) },
    { nav: "Investigations", region: (p: Page) => p.getByRole("region", { name: "investigation" }) },
    { nav: "Since you were away", region: (p: Page) => p.getByRole("region", { name: "morning report" }) },
    { nav: "Metric graph", region: (p: Page) => p.getByRole("region", { name: "metric graph" }) },
    { nav: "Metric tree", region: (p: Page) => p.getByRole("region", { name: "metric tree" }) },
    { nav: "Track record", region: (p: Page) => p.getByRole("region", { name: "bench scorecard" }) },
  ];

  test("?fx=1 loads Argus Ice: theme set, loader gone, KPI cards for every north-star metric, no errors", async ({ page }) => {
    const errors = watchFxErrors(page);
    await open(page, FX);
    await expect(navButton(page, "Dashboard")).toHaveAttribute("aria-current", "page");

    const graph = (await (await page.request.get(`${base}/graph`)).json()) as { nodes: { id: string; label: string; north_star?: boolean }[] };
    const stars = graph.nodes.filter((n) => n.north_star);
    expect(stars.length, "the graph has north-star metrics").toBeGreaterThan(0);
    const kpis = page.getByRole("region", { name: "north-star metrics" });
    await expect(kpis.getByRole("button")).toHaveCount(stars.length);
    for (const star of stars) await expect(kpis.locator(`button[title^="${star.label}:"]`), star.id).toBeVisible();
    await expect(kpis.locator(".fx-kpi-human")).toContainText("Human actions");
    await expect(dashboard(page).locator("p").first()).toContainText(`${stars.length} north-star metrics`);
    expect(errors()).toEqual([]);
  });

  test("S1 at 64x: INC-0001 SUPPORTED CAUSE in DE / android / PayCo on the dashboard and in the feed; its report opens", async ({ page }) => {
    const errors = watchFxErrors(page);
    await open(page, FX);
    await runToVerdict(page);

    const row = dashboard(page).locator(".fx-incident").filter({ hasText: "INC-0001" });
    await expect(row).toHaveCount(1);
    await expect(row.locator(".pill.SUPPORTED_CAUSE")).toHaveText("SUPPORTED CAUSE");
    const path = row.getByLabel("affected path");
    for (const s of ["DE", "android", "PayCo"]) await expect(path).toContainText(s);

    const card = incidentCard(page);
    await expect(card).toHaveCount(1);
    await expect(card).toBeVisible();
    await expect(card.locator(".pill.SUPPORTED_CAUSE")).toHaveText("SUPPORTED CAUSE");
    for (const s of ["DE", "android", "PayCo"]) await expect(card.locator(".segs")).toContainText(s);

    await row.getByRole("button", { name: "Open report" }).click();
    const sheet = page.getByRole("dialog", { name: "Incident INC-0001" });
    await expect(sheet).toBeVisible();
    await expect(sheet.getByRole("heading", { name: "What happened" })).toBeVisible();
    await expect(sheet.locator(".sheet-top .pill.SUPPORTED_CAUSE")).toHaveText("SUPPORTED CAUSE");
    await expect(sheet.locator(".sheet-title")).toContainText("PayCo");
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();
    expect(errors()).toEqual([]);
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
    // Start from Scorecard so that "1" is a change of the host's tab.
    await navButton(page, "Track record").click();
    const KEYS: [string, string][] = [
      ["1", "Metric graph"],
      ["2", "Metric tree"],
      ["3", "Investigations"],
      ["4", "Since you were away"],
      ["5", "Track record"],
    ];
    for (const [key, nav] of KEYS) {
      await page.keyboard.press(key);
      await expect(navButton(page, nav), `key ${key}`).toHaveAttribute("aria-current", "page");
      await expect(SECTIONS.find((s) => s.nav === nav)!.region(page)).toBeVisible();
    }
    await navButton(page, "Dashboard").click();
    await expect(dashboard(page)).toBeVisible();
    expect(errors()).toEqual([]);
  });

  test("key 1 on the dashboard opens the metric graph", async ({ page }) => {
    // The view host is already on its graph tab under the dashboard, so "1" changes no aria-selected and
    // watchHost (web/src/fx/nav.ts) never hears it: the dashboard stays. Remove this line once fixed.
    test.fail(true, "key 1 does nothing on the dashboard: the host tab is already 'graph' (web/src/fx/nav.ts watchHost)");
    await open(page, FX);
    await expect(navButton(page, "Dashboard")).toHaveAttribute("aria-current", "page");
    await page.keyboard.press("1");
    await expect(navButton(page, "Metric graph")).toHaveAttribute("aria-current", "page", { timeout: 2_000 });
  });

  test("the metric graph view renders the 3D scene (canvas) or, without WebGL2, the classic graph", async ({ page }) => {
    const errors = watchFxErrors(page);
    await open(page, FX);
    await navButton(page, "Metric graph").click();
    await expect(page.getByRole("region", { name: "metric graph" })).toBeVisible();
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
    expect(errors()).toEqual([]);
  });

  test("?fx=night sets data-fx=night", async ({ page }) => {
    const errors = watchFxErrors(page);
    await open(page, "/?fx=night&fxintro=0", "night");
    await expect(dashboard(page)).toBeVisible();
    expect(errors()).toEqual([]);
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
    await expect(navButton(page, "Dashboard")).toHaveAttribute("aria-current", "page");

    // demo mode restarted the replay itself at its default speed 2 (web/src/views/demo/demo.ts)
    await expect.poll(async () => (await health(page)).stream, { timeout: 10_000, message: "demo mode restarts the replay" }).not.toBe(before);
    expect((await health(page)).run.speed).toBe(2);
    // fast-forward the quiet hours to the morning of the anomaly (Sat 21 Nov 20:00); the page is not touched.
    // Then 4x: the walk stays readable, and the rest of the run (30 h, then the 8 s loop linger) outlasts
    // the report hold (3.5 s + 12 s), so the loop does not restart the choreography under the test.
    await fastForward(page, "2026-11-21T12:00:00", 4);

    // the first step switches to the investigation by itself, the captions follow the walk
    await expect(navButton(page, "Investigations")).toHaveAttribute("aria-current", "page", { timeout: 15_000 });
    await expect(page.getByRole("region", { name: "investigation" })).toBeVisible();
    await expect(caption).toHaveClass(/b-(checks|localised|suspects|verdict|monitoring)/);
    await expect(caption).toHaveText(/Verdict: supported cause in DE · android · PayCo/, { timeout: 15_000 });

    // 3.5 s after the verdict the report opens; `hold` (12 s) later it closes and the page goes back to the overview
    const sheet = page.getByRole("dialog", { name: "Incident INC-0001" });
    await expect(sheet).toBeVisible({ timeout: 8_000 });
    await expect(sheet.locator(".sheet-top .pill.SUPPORTED_CAUSE")).toHaveText("SUPPORTED CAUSE");
    await expect(page.getByRole("status").locator(".cap-line")).toBeVisible();
    await expect(sheet).toBeHidden({ timeout: 16_000 });
    await expect(navButton(page, "Dashboard")).toHaveAttribute("aria-current", "page", { timeout: 3_000 });
    await expect(page.locator("html")).toHaveClass(/\bargus-demo\b/);
    expect(errors()).toEqual([]);
  });

  test("QA screenshots of the fx layer (ARGUS_E2E_SHOTS=1)", async ({ page }) => {
    test.skip(!SHOTS, "set ARGUS_E2E_SHOTS=1 to capture the fx screenshots");
    test.setTimeout(150_000);
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
    await expect(dashboard(page).locator(".fx-running .fx-steps li")).toHaveCount(5, { timeout: 30_000 });
    await post(page, { action: "pause" });
    await both("dashboard-midrun");

    // 2. INC-0001 explained, before it starts to recover (still 1x, paused on the verdict)
    await post(page, { action: "play" });
    await expect(dashboard(page).locator(".fx-incident .pill.SUPPORTED_CAUSE")).toBeVisible({ timeout: 30_000 });
    await post(page, { action: "pause" });
    await both("dashboard-explained");

    // 3. the incident report
    await dashboard(page).getByRole("button", { name: "Open report" }).click();
    const sheet = page.getByRole("dialog", { name: "Incident INC-0001" });
    await expect(sheet.getByRole("heading", { name: "What happened" })).toBeVisible();
    await shot("incident-report-1920");
    await page.keyboard.press("Escape");
    await expect(sheet).toBeHidden();

    // 4. the metric graph view
    await navButton(page, "Metric graph").click();
    await shot("graph-1920");

    // 5. the night theme, same paused state
    await open(page, "/?fx=night&fxintro=0", "night");
    // the night preview materializes slower under SwiftShader (about 4 s)
    await page.waitForTimeout(3000);
    await shot("night-1920");

    // 6. the recording URL with captions mid-play (the investigation walking at 1x)
    const before = (await health(page)).stream;
    await page.goto(base + RECORDING);
    await expect.poll(async () => (await health(page)).stream, { timeout: 10_000 }).not.toBe(before);
    await fastForward(page, "2026-11-21T16:00:00", 1);
    await expect(navButton(page, "Investigations")).toHaveAttribute("aria-current", "page", { timeout: 15_000 });
    await expect(page.getByRole("status").locator(".cap-line")).toHaveClass(/b-(localised|suspects)/, { timeout: 20_000 });
    await shot("demo-captions-1920");
  });
});

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
    if (req.url().endsWith("/events")) return;
    errors.push(`failed: ${req.method()} ${req.url()} ${req.failure()?.errorText ?? ""}`);
  });
  page.on("response", (res) => {
    if (res.status() >= 400 && !allowed(res.status())) errors.push(`http ${res.status()}: ${res.request().method()} ${res.url()}`);
  });
  return () => errors;
}
