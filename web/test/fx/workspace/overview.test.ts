// The overview's numbers and words against the recorded runs: the health score is the plain average of its four
// checks, it drops while S1's incident is open and is back at 100 once it resolves, the tiles count what the
// stream reported, the week's tasks come from the incidents' proposed actions, and the plain words never leak an
// internal term.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { backFrom, followHost, initialLocation } from "../../../src/fx/nav";
import { health, tasks, tiles } from "../../../src/fx/workspace/health";
import { gloss, GLOSSARY, storyHeadline, tip, unusualness, wherePhrase, whereCells } from "../../../src/fx/workspace/plain";
import { emptyView, fold, type RunView } from "../../../src/lib/store";
import type { Incident } from "../../../src/lib/types";
import { loadEvents, loadGraph } from "../scene/fixtures";

const SCENARIOS = ["", "quiet", "s2", "s3", "s4", "s5"];

function replay(scenario: string, each?: (view: RunView) => void): RunView {
  let view = emptyView("s", "replay");
  for (const event of loadEvents(scenario)) {
    view = fold(view, event);
    each?.(view);
  }
  return view;
}

function incidents(scenario = ""): Incident[] {
  const path = fileURLToPath(new URL(`../../../../fixtures/${scenario ? `${scenario}/` : ""}incidents.json`, import.meta.url));
  return JSON.parse(readFileSync(path, "utf8")) as Incident[];
}

describe("the shop health score", () => {
  it.each(SCENARIOS)("is the plain average of its four checks at every hour (%s)", (scenario) => {
    const graph = loadGraph(scenario);
    replay(scenario, (view) => {
      const h = health(view, graph);
      expect(h.checks.map((c) => c.key)).toEqual(["data", "metrics", "formulas", "incidents"]);
      for (const c of h.checks) {
        expect(c.passed).toBeLessThanOrEqual(c.total);
        expect(c.share).toBeCloseTo(c.total ? c.passed / c.total : 1, 9);
      }
      if (!view.tick) expect(h.score).toBeNull();
      else expect(h.score).toBe(Math.round((100 * h.checks.reduce((s, c) => s + c.share, 0)) / 4));
    });
  });

  it("drops while S1's incident is open and is back at 100 once it resolves", () => {
    const graph = loadGraph();
    const seen: number[] = [];
    const end = replay("", (view) => {
      const open = Object.values(view.incidents).some((i) => i.state !== "resolved");
      const h = health(view, graph);
      if (open && h.score !== null) seen.push(h.score);
    });
    expect(seen.length).toBeGreaterThan(0);
    expect(Math.max(...seen)).toBeLessThan(100);
    expect(health(end, graph).score).toBe(100);
  });

  it("stays at 100 through the quiet week", () => {
    const graph = loadGraph("quiet");
    const end = replay("quiet");
    expect(health(end, graph).score).toBe(100);
  });
});

describe("the KPI tiles", () => {
  it("count what the stream reported, in plain words", () => {
    const graph = loadGraph();
    const end = replay("");
    const byKey = Object.fromEntries(tiles(end, graph).map((t) => [t.key, t]));
    const lost = Object.values(end.incidents).reduce((s, i) => s + Math.abs(i.severity_eur), 0);
    expect(byKey.cost.value).toBe(`€${Math.round(lost).toLocaleString("en-US")}`);
    expect(byKey.open.value).toBe("0");
    expect(byKey.noise.value).toBe(String(end.wiggles));
    expect(byKey.human.value).toBe("0");
    for (const t of Object.values(byKey)) expect(`${t.label} ${t.change}`).not.toMatch(/\|z\||series-hours|LMDI|edge test|wiggle/i);
    // one chart point per scored hour the store keeps
    expect(byKey.open.series.length).toBe(end.hours.length);
    expect(end.hours.length).toBe(Math.min(end.ticks, 72));
  });
});

describe("the week's tasks", () => {
  it("list every incident with a proposed action, with its cost and the plain headline", () => {
    const graph = loadGraph();
    const list = tasks(incidents(), graph);
    expect(list.length).toBe(1);
    expect(list[0].headline).toMatch(/^Payment success fell \d+\.\d% for Android in Germany via PayCo$/);
    expect(list[0].eur).toBeGreaterThan(0);
    expect(list[0].action).toMatch(/\.$/);
  });

  it("put open incidents first, then the most expensive", () => {
    const base = incidents()[0];
    const make = (id: string, state: Incident["state"], severity: number): Incident => ({ ...base, id, state, severity_eur: severity });
    const order = tasks([make("A", "resolved", 900), make("B", "open", 10), make("C", "open", 50)], null).map((t) => t.id);
    expect(order).toEqual(["C", "B", "A"]);
  });
});

describe("plain words", () => {
  it("say where in words a person uses", () => {
    expect(wherePhrase({ provider: "PayCo", country: "DE", platform: "android" })).toBe("Android in Germany via PayCo");
    expect(wherePhrase({})).toBe("the whole shop");
    expect(whereCells({ country: "FR" })).toEqual([{ dim: "country", name: "Country", value: "France" }]);
    expect(storyHeadline(null, "orders", 12.345, { country: "DE" })).toBe("Orders rose 12.3% for Germany");
  });

  it("put the watcher's lines into words", () => {
    expect(unusualness(null, 2, 5).word).toBe("not checked this hour");
    expect(unusualness(1.9, 2, 5).tone).toBe("ok");
    expect(unusualness(2, 2, 5).tone).toBe("watch");
    expect(unusualness(5, 2, 5).tone).toBe("alarm");
  });

  it("explain every internal term once, by its term or its plain name", () => {
    const terms = GLOSSARY.map((g) => g.term.toLowerCase());
    expect(new Set(terms).size).toBe(terms.length);
    for (const t of ["|z|", "LMDI", "Edge test", "Series-hours", "Holdout", "Receipt", "pass@1"]) expect(gloss(t), t).toBeDefined();
    expect(gloss("formula check")?.term).toBe("Edge test");
    expect(tip("LMDI")).toMatch(/^Exact split \(LMDI\): /);
    expect(tip("unknown term")).toBeUndefined();
  });
});

describe("navigation", () => {
  it("deep-links to a page or an incident, else starts on the overview", () => {
    expect(initialLocation("")).toEqual({ section: "dashboard", incident: null });
    expect(initialLocation("?view=tree")).toEqual({ section: "tree", incident: null });
    expect(initialLocation("?view=glossary")).toEqual({ section: "glossary", incident: null });
    expect(initialLocation("?view=incident&incident=INC-0001")).toEqual({ section: "incident", incident: "INC-0001" });
    expect(initialLocation("?view=incident")).toEqual({ section: "incidents", incident: null });
    expect(initialLocation("?view=nonsense")).toEqual({ section: "dashboard", incident: null });
  });

  it("returns from an incident to where it was opened, and demo mode's return to the graph means the overview", () => {
    expect(backFrom({ section: "investigation", incident: null })).toEqual({ section: "investigation", incident: null });
    expect(backFrom({ section: "incident", incident: "INC-0001" })).toEqual({ section: "dashboard", incident: null });
    expect(followHost("graph", true)).toBe("dashboard");
    expect(followHost("graph", false)).toBe("graph");
  });
});

describe("the visualization's incident story", () => {
  it("walks S1 from revenue down the formulas to payment success, then the cause and the ruled-out suspects", async () => {
    const { formulaChain, storyOf, storyFocus } = await import("../../../src/fx/workspace/story");
    const graph = loadGraph();
    expect(formulaChain(graph, "payment_success_rate")).toEqual({ nodes: ["gmv", "orders", "cvr", "payment_success_rate"], edges: ["f_gmv", "f_orders", "f_cvr"] });
    const story = storyOf(graph, incidents()[0]);
    expect(story.steps.map((s) => s.kind)).toEqual(["effect", "effect", "effect", "root", "cause", "ruled", "ruled"]);
    expect(story.steps[0].focus.tags?.gmv).toMatch(/^-€[\d,]+$/);
    expect(story.steps[3].focus.tags?.payment_success_rate).toMatch(/^-\d+\.\d%$/);
    expect(story.steps[4].focus.logs).toEqual(["log_provider_status"]);
    expect(story.steps.filter((s) => s.kind === "ruled").every((s) => s.focus.tags && Object.values(s.focus.tags)[0].startsWith("✕"))).toBe(true);
    const all = storyFocus(story, story.steps.length - 1);
    expect(all.nodes).toEqual(["gmv", "orders", "cvr", "payment_success_rate"]);
    expect(new Set(all.logs)).toEqual(new Set(["log_provider_status", "log_deploys"]));
    expect(storyFocus(story, 0).nodes).toEqual(["gmv"]);
  });

  it("finds a chain for every recorded incident's root", async () => {
    const { formulaChain } = await import("../../../src/fx/workspace/story");
    for (const scenario of ["s4", "s5"]) {
      const graph = loadGraph(scenario);
      for (const inc of incidents(scenario)) {
        const chain = formulaChain(graph, inc.findings.root?.node ?? inc.root_node);
        expect(chain.nodes[chain.nodes.length - 1]).toBe(inc.findings.root?.node ?? inc.root_node);
        expect(chain.edges.length).toBe(chain.nodes.length - 1);
      }
    }
  });
});
