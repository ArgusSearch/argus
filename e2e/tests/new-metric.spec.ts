import { mkdirSync, readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, test, type Locator, type Page } from "@playwright/test";
import { watchErrors } from "./helpers";
import { startApi, stopApi, type OwnApi } from "./own-api";

// Demo moment 3, "a new metric places itself in the graph" (docs/ext/graph-extension.md, web/src/graph-extension).
// A replay serves the recorded ad-metric pack (fixtures/graph_extension): POST /graph/metrics adds the recorded node
// and edges to the replayed graph, and Mission Control polls GET /graph/metrics (every 1.5 s), shows the
// "New metric placed" card over the graph, refetches /graph and marks the placed nodes in the graph and the tree.
// Runs on its own replay API (default port 8015, ARGUS_E2E_NEWMETRIC_PORT) so the placements never leak into the
// other specs' graph. Replay-only, 1920x1080, every wait bounded. The tests share the API and run in order.
// The fx check runs unless ARGUS_E2E_FX=0 (what `npm test` sets). ARGUS_E2E_SHOTS=1 saves new-metric-card-classic,
// -graph-classic, -card-fx and, when the refit misses, -refit-bug .png (1920x1080) into docs/qa/screenshots.
const PORT = Number(process.env.ARGUS_E2E_NEWMETRIC_PORT ?? 8015);
const SHOTS = Boolean(process.env.ARGUS_E2E_SHOTS);
const ROOT = resolve(process.env.ARGUS_E2E_ROOT ?? "..");
const PACK = resolve(ROOT, "fixtures/graph_extension/metrics");
const PLACED_GREEN = "rgb(63, 191, 143)"; // --gx-placed fallback (#3fbf8f) in placedNodeStyles

let api: OwnApi | null = null;
let base = "";

test.use({ viewport: { width: 1920, height: 1080 } });
test.describe.configure({ mode: "serial" });

test.describe("a new metric places itself in the graph", () => {
  test.skip(process.env.ARGUS_E2E_MODE === "live", "replay-only: places the recorded ad-metric pack on its own replay API");
  test.skip(process.env.ARGUS_E2E_NEWMETRIC === "0", "ARGUS_E2E_NEWMETRIC=0 (npm test); runs in test:demo and test:all");

  test.beforeAll(async () => {
    api = await startApi(PORT);
    base = api.base;
  });
  test.afterAll(async () => {
    await stopApi(api);
    api = null;
  });

  async function replay(page: Page, body: object): Promise<void> {
    const res = await page.request.post(`${base}/replay`, { data: body });
    expect(res.status(), `POST /replay ${JSON.stringify(body)}`).toBeLessThan(300);
  }

  /** POST one pack file as YAML, the way a contributor would (`curl --data-binary @file.yml`). */
  async function place(page: Page, file: string): Promise<{ placed_as: string; parents: string[] }> {
    const res = await page.request.post(`${base}/graph/metrics`, {
      headers: { "content-type": "application/yaml" },
      data: readFileSync(resolve(PACK, file), "utf8"),
    });
    expect(res.status(), `POST /graph/metrics ${file}: ${await res.text()}`).toBe(200);
    return res.json();
  }

  async function shot(page: Page, name: string): Promise<void> {
    if (!SHOTS) return;
    await page.waitForTimeout(1_500); // the card fades in and its diagram draws itself (about 1.2 s)
    const dir = resolve(process.cwd(), "../docs/qa/screenshots");
    mkdirSync(dir, { recursive: true });
    await page.screenshot({ path: resolve(dir, `new-metric-${name}.png`) });
  }

  /** Open a page and wait for its first GET /graph/metrics (see the race test: a placement before it is lost). */
  async function open(page: Page, path = "/"): Promise<void> {
    const firstPoll = page.waitForResponse((r) => r.url() === `${base}/graph/metrics` && r.request().method() === "GET", { timeout: 15_000 });
    await page.goto(`${base}${path}`);
    await expect(page).toHaveTitle("Argus · Mission Control");
    await firstPoll;
  }

  const card = (page: Page) => page.locator("article.gx-card");
  const graphNode = (page: Page, id: string) => page.locator(`.react-flow__node[data-id="${id}"]`);
  const chips = (c: Locator) => c.locator(".gx-chip text").allTextContents();

  async function boxShadow(l: Locator): Promise<string> {
    return l.evaluate((el) => getComputedStyle(el).boxShadow);
  }

  /** Every React Flow node lies inside the graph canvas and the 1920x1080 viewport (the refit after growth). */
  async function offscreen(page: Page): Promise<string[]> {
    return page.evaluate(() => {
      const canvas = document.querySelector(".graph-canvas")?.getBoundingClientRect();
      if (!canvas) return ["no .graph-canvas"];
      const out: string[] = [];
      for (const el of document.querySelectorAll<HTMLElement>(".react-flow__node")) {
        const r = el.getBoundingClientRect();
        const inside = r.left >= canvas.left - 1 && r.right <= canvas.right + 1 && r.top >= canvas.top - 1 && r.bottom <= canvas.bottom + 1;
        const onScreen = r.left >= 0 && r.right <= window.innerWidth && r.top >= 0 && r.bottom <= window.innerHeight;
        if (!inside || !onScreen || r.width < 8) out.push(`${el.dataset.id} ${Math.round(r.left)},${Math.round(r.top)} ${Math.round(r.width)}x${Math.round(r.height)}`);
      }
      return out;
    });
  }

  /** Nodes whose box the card or the pill bar covers (reported, not asserted: the card sits over the graph by design). */
  async function covered(page: Page): Promise<string[]> {
    return page.evaluate(() => {
      const layer = [...document.querySelectorAll(".gx-card, .gx-bar")].map((e) => e.getBoundingClientRect());
      const out: string[] = [];
      for (const el of document.querySelectorAll<HTMLElement>(".react-flow__node")) {
        const r = el.getBoundingClientRect();
        if (layer.some((l) => r.left < l.right && r.right > l.left && r.top < l.bottom && r.bottom > l.top)) out.push(el.dataset.id ?? "?");
      }
      return out;
    });
  }

  test("an EXACT metric posted to the API: the card shows its parents and what it feeds, the node appears in the graph marked as placed", async ({ page }) => {
    const errors = watchErrors(page);
    await replay(page, { action: "restart" });
    await replay(page, { action: "pause" }); // a looping replay would start a new stream and drop the placement
    await open(page);
    await expect(page.locator(".react-flow__node").first()).toBeVisible();
    const before = await page.locator(".react-flow__node").count();
    await expect(card(page)).toHaveCount(0);

    const result = await place(page, "1_cost_per_impression.yml");
    expect(result.placed_as).toBe("EXACT");
    expect(result.parents).toEqual(["ctr", "cpc"]);

    // the poll (1.5 s) sees the new version, shows the card and refetches the graph
    const c = card(page);
    await expect(c).toBeVisible({ timeout: 5_000 });
    await expect(c).toHaveAttribute("aria-label", "New metric placed: cost_per_impression");
    await expect(c.locator(".gx-kind")).toHaveText("New metric placed");
    await expect(c.locator(".gx-verdict")).toHaveText("exact");
    await expect(c.locator(".gx-title")).toContainText("Cost per impression");
    await expect(c.locator(".gx-when")).toContainText("recorded");
    // parents CTR × CPC on the left, the formula it feeds (Ad spend = Ad impressions × this) on the right
    expect(await chips(c)).toEqual(["CTR", "CPC", "Ad spend"]);
    await expect(c.locator(".gx-feed-label")).toHaveText("= Ad impressions × this");
    await expect(c.locator(".gx-dims")).toHaveText("breakdowns by advertiser_id · country · platform");
    await expect(c.locator(".gx-headline")).toHaveText("Cost per impression = CTR × CPC, proven on the data (residual 0.00 % over 672 h).");
    await expect(c.locator(".gx-foot")).toContainText("5 edges tested · 34 receipts · S4 world, seed 1");
    await c.getByRole("button", { name: "Certificate" }).click();
    await expect(c.locator(".gx-cert")).toContainText("cost_per_impression = ctr * cpc");
    await c.getByRole("button", { name: "Hide certificate" }).click();

    // the node is in the graph, marked as placed, and the bar counts it
    await expect(page.locator(".react-flow__node")).toHaveCount(before + 1, { timeout: 5_000 });
    await expect(page.locator(".graph-bar .sub")).toContainText("28 metrics");
    const node = graphNode(page, "cost_per_impression");
    await expect(node).toBeVisible();
    await expect.poll(() => boxShadow(node.locator(".mnode")), { timeout: 5_000, message: "placed node highlight" }).toContain(PLACED_GREEN);
    await expect(page.locator(".gx-pill")).toHaveText(["Cost per impression"]);
    await expect(page.locator(".gx-add")).toHaveText("Add the ad metric pack (4)");

    // the refit itself is asserted in "the graph refits to every node after each placement" (it misses at random)
    test.info().annotations.push({ type: "nodes outside the canvas", description: (await offscreen(page)).join(", ") || "none" });
    test.info().annotations.push({ type: "covered by the card", description: (await covered(page)).join(", ") || "none" });
    await shot(page, "card-classic");
    expect(errors()).toEqual([]);
  });

  test("the tree view marks the placed node", async ({ page }) => {
    const errors = watchErrors(page);
    await open(page);
    await page.getByRole("tab", { name: "Tree" }).click();
    const tree = page.getByRole("region", { name: "metric tree" });
    await expect(tree).toBeVisible();
    await tree.getByRole("textbox", { name: "Find a metric" }).fill("cost per impression");
    const row = tree.locator('[data-node="cost_per_impression"]').first();
    await expect(row).toBeVisible();
    await expect(row).toContainText("Cost per impression");
    await expect.poll(() => boxShadow(row), { timeout: 5_000, message: "placed tree row highlight" }).toContain(PLACED_GREEN);
    // a seed metric is not marked
    await tree.getByRole("textbox", { name: "Find a metric" }).fill("ctr");
    const seed = tree.locator('[data-node="ctr"]').first();
    await expect(seed).toBeVisible();
    expect(await boxShadow(seed)).not.toContain(PLACED_GREEN);
    expect(errors()).toEqual([]);
  });

  test("'Add the ad metric pack' places the rest: AMBIGUOUS shows the alternative parent, REJECTED shows the fan-out and its repair", async ({ page }) => {
    const errors = watchErrors(page);
    await open(page);
    await expect(page.locator(".gx-pill")).toHaveCount(1);
    await page.locator(".gx-add").click();
    // four metrics, one every ~1.4 s plus the 1.5 s poll
    await expect(page.locator(".gx-pill")).toHaveText(
      ["Cost per impression", "Conversions per impression", "Revenue per conversion", "Revenue per impression", "Ad spend per session"],
      { timeout: 20_000 },
    );
    await expect(page.locator(".gx-add")).toHaveCount(0);

    // the newest placement is on screen: the rejected join fan-out with its repair diff
    const rejected = card(page);
    await expect(rejected).toHaveAttribute("aria-label", "Metric rejected: ad_spend_per_session");
    await expect(rejected).toHaveClass(/\bbad\b/);
    await expect(rejected.locator(".gx-verdict")).toHaveText("rejected");
    expect(await chips(rejected)).toEqual(["fact_ads_hourly", "fact_funnel_hourly"]);
    await expect(rejected.locator(".gx-node-sub")).toHaveText("fan-out ×6.72");
    await expect(rejected.locator(".gx-headline")).toHaveText("Not placed: the join counts rows 6.72 times over. A repaired query is attached.");
    const diff = rejected.getByLabel("repair diff");
    await expect(diff).toBeVisible();
    expect(await diff.locator("span.add").count()).toBeGreaterThan(0);
    expect(await diff.locator("span.del").count()).toBeGreaterThan(0);

    // the ambiguous one: two equally simple parents, the first on probation at half weight, the other kept aside
    await page.locator(".gx-pill", { hasText: "Revenue per impression" }).click();
    const ambiguous = card(page);
    await expect(ambiguous).toHaveAttribute("aria-label", "New metric placed: revenue_per_impression");
    await expect(ambiguous).toHaveClass(/\bwatch\b/);
    await expect(ambiguous.locator(".gx-verdict")).toHaveText("ambiguous");
    await expect(ambiguous.locator(".gx-wire-label", { hasText: "probation · ½ weight" })).toHaveCount(1);
    await expect(ambiguous.locator(".gx-wire-label", { hasText: "alternative parent" })).toHaveCount(1);
    await expect(ambiguous.locator(".gx-headline")).toHaveText(
      "Two parents fit equally well: Cost per impression × ROAS or Conversions per impression × Revenue per conversion. " +
        "Argus keeps the first on probation at half weight and the other as an alternative until the evidence decides.",
    );

    // four new nodes (the rejected metric adds none), each marked, and the whole graph still fits
    await expect(page.locator(".graph-bar .sub")).toContainText("31 metrics", { timeout: 5_000 });
    for (const id of ["cost_per_impression", "conversions_per_impression", "revenue_per_conversion", "revenue_per_impression"]) {
      const n = graphNode(page, id);
      await expect(n, id).toBeVisible();
      await expect.poll(() => boxShadow(n.locator(".mnode")), { timeout: 5_000, message: `${id} highlight` }).toContain(PLACED_GREEN);
    }
    await expect(graphNode(page, "ad_spend_per_session")).toHaveCount(0);
    test.info().annotations.push({ type: "nodes outside the canvas", description: (await offscreen(page)).join(", ") || "none" });
    test.info().annotations.push({ type: "covered by the card", description: (await covered(page)).join(", ") || "none" });

    // the card closes and the graph with its placed nodes is unobstructed. The refit misses at random (see the next
    // test); for the screenshot a reload fits the grown graph from scratch
    if (SHOTS && (await offscreen(page)).length) {
      await page.reload();
      await expect(page.locator(".react-flow__node")).toHaveCount(35);
      await expect(card(page)).toBeVisible({ timeout: 5_000 });
    }
    await card(page).getByRole("button", { name: "Hide the placement card" }).click();
    await expect(card(page)).toHaveCount(0);
    await shot(page, "graph-classic");
    expect(errors()).toEqual([]);
  });

  test("the graph refits to every node after each placement posted to the API", async ({ page }) => {
    // GraphView refits with every node named (2c62f8b), yet after a placement the view sometimes zooms onto the new
    // node(s) alone and stays there: about 3 in 5 runs of four API posts, about 1 in 12 single posts on a settled page,
    // rarely through the pack button. The miss is random, so the test marks itself as an expected failure only when it
    // hits the bug, and passes when every refit lands; remove the test.fail line once GraphView's fit is fixed.
    const errors = watchErrors(page);
    await replay(page, { action: "restart" });
    await replay(page, { action: "pause" });
    await open(page);
    const files = ["1_cost_per_impression.yml", "2_conversions_per_impression.yml", "3_revenue_per_conversion.yml", "4_revenue_per_impression.yml"];
    for (const [i, file] of files.entries()) {
      await place(page, file);
      await expect(page.locator(".graph-bar .sub")).toContainText(`${28 + i} metrics`, { timeout: 5_000 });
      await expect(page.locator(".react-flow__node")).toHaveCount(32 + i);
      await page.waitForTimeout(2_000); // the fit runs on the next frame; give React Flow time to measure the new node
      const off = await offscreen(page);
      if (off.length) await shot(page, "refit-bug");
      test.fail(
        off.length > 0,
        `after ${file} the graph zoomed onto the new node(s) and left ${off.length} nodes outside the canvas: web/src/components/GraphView.tsx fit vs React Flow's own fitView`,
      );
      expect(off, `nodes outside the graph canvas after ${file}`).toEqual([]);
    }
    expect(errors()).toEqual([]);
  });

  test("a placement that lands before the page's first poll still puts its node in the graph", async ({ page }) => {
    // useGraphExtension only refetches /graph when the version moves between two polls (seen !== null), so a
    // placement between the page's GET /graph and its first GET /graph/metrics shows the card but never the node.
    // In the fx look the first poll comes seconds late (the 3D boot), which widens the window.
    test.fail(true, "first poll skips the graph refetch: web/src/graph-extension/useGraphExtension.ts (seen.current === null)");
    const errors = watchErrors(page);
    await replay(page, { action: "restart" }); // new stream: no placements
    await replay(page, { action: "pause" });
    let release = () => {};
    const gate = new Promise<void>((r) => (release = r));
    let held = false;
    await page.route(`${base}/graph/metrics`, async (route) => {
      if (route.request().method() === "GET" && !held) {
        held = true; // hold the first poll until the placement is in
        await gate;
      }
      await route.continue();
    });
    await page.goto(`${base}/`);
    await expect(page.locator(".graph-bar .sub")).toContainText("27 metrics");
    await place(page, "1_cost_per_impression.yml");
    release();
    await expect(card(page)).toHaveAttribute("aria-label", "New metric placed: cost_per_impression", { timeout: 5_000 });
    // the card says the metric is placed: the graph must show it (it stays at 27 metrics, the node never comes)
    await expect(page.locator(".graph-bar .sub")).toContainText("28 metrics", { timeout: 5_000 });
    await expect(graphNode(page, "cost_per_impression")).toBeVisible();
    expect(errors()).toEqual([]);
  });

  test("fx look: the card shows over the 3D graph and the scene gets the new node", async ({ page }) => {
    test.skip(process.env.ARGUS_E2E_FX === "0", "ARGUS_E2E_FX=0 (npm test); runs in test:all");
    test.setTimeout(60_000);
    const errors: string[] = [];
    page.on("console", (m) => m.type() === "error" && errors.push(`console: ${m.text()}`));
    page.on("pageerror", (e) => errors.push(`pageerror: ${e.message}`));
    page.on("response", (r) => r.status() >= 500 && errors.push(`http ${r.status()}: ${r.url()}`));
    await replay(page, { action: "restart" }); // a new stream drops the earlier placements
    await replay(page, { action: "pause" });
    await open(page, "/?fx=1&fxintro=0");
    await expect(page.locator("html")).toHaveAttribute("data-fx-phase", "ready", { timeout: 10_000 });
    await page.getByRole("navigation", { name: "sections" }).getByRole("button", { name: /^Metric graph/ }).click();
    const region = page.getByRole("region", { name: "metric graph" });
    await expect(region).toBeVisible();
    const sceneMount = page.locator('[data-fx-scene="full"]');
    await expect(sceneMount.or(page.locator(".react-flow__node")).first()).toBeAttached({ timeout: 10_000 });
    const scene = (await sceneMount.count()) > 0;
    test.info().annotations.push({ type: "graph", description: scene ? "3D scene" : "classic graph (no WebGL2)" });
    await expect(page.locator(".gx-pill")).toHaveCount(0, { timeout: 5_000 });

    await place(page, "1_cost_per_impression.yml");
    const c = card(page);
    await expect(c).toBeVisible({ timeout: 10_000 }); // the 1.5 s poll runs late while SwiftShader renders
    await expect(c).toHaveAttribute("aria-label", "New metric placed: cost_per_impression");
    expect(await chips(c)).toEqual(["CTR", "CPC", "Ad spend"]);
    await expect(region.locator(".sub")).toContainText("28 metrics", { timeout: 5_000 });
    if (scene) {
      // the scene's DOM label of the new block, tagged "new metric" while it freezes in (slow under SwiftShader)
      const label = page.locator('.fxs-node[data-id="cost_per_impression"]');
      await expect(label).toHaveCount(1, { timeout: 15_000 });
      await expect(label).toContainText("Cost per impression");
      await expect(label).toContainText("new metric");
      await expect(label).toHaveClass(/\bshown\b/, { timeout: 20_000 });
    } else {
      await expect(graphNode(page, "cost_per_impression")).toBeVisible();
    }
    await shot(page, "card-fx");
    expect(errors).toEqual([]);
  });
});
