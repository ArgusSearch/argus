// The scene model against the recorded runs: every block and link carries the state the 2D graph shows at
// the same replay position, the trace follows the trail, and a new graph version reports exactly what it adds.
import { describe, expect, it } from "vitest";
import { sceneModel, ruledOut, nodeTitle, type SceneModel } from "../../../src/fx/scene/model";
import { emptyView, fold, freshAnomaly, type RunView } from "../../../src/lib/store";
import type { ArgusEvent, Graph } from "../../../src/lib/types";
import { loadEvents, loadGraph } from "./fixtures";

/**
 * An independent transcription of GraphView's state rules (web/src/components/GraphView.tsx, the node and edge
 * maps of the component body): what the 2D graph shows for each metric, log and link.
 */
function graphViewOracle(graph: Graph, view: RunView) {
  const roots = new Map<string, string>();
  const symptoms = new Map<string, string>();
  const resolved = new Set<string>();
  for (const inc of Object.values(view.incidents)) {
    if (inc.state === "resolved") resolved.add(inc.root_node);
    else roots.set(inc.root_node, inc.verdict === "SUPPORTED_CAUSE" ? "root cause" : "anomaly");
  }
  for (const note of view.notes) if (note.node && note.reason.includes("symptom of")) symptoms.set(note.node, "symptom");
  const fNodes = new Set(view.focus?.nodes ?? []);
  const fLogs = new Set(view.focus?.logs ?? []);
  const fEdges = new Set((view.focus?.edges ?? []).filter((e) => !e.startsWith("b_")));
  const split = (view.focus?.edges ?? []).filter((e) => e.startsWith("b_"));
  const fresh = freshAnomaly(view);
  const scored = new Set(view.tick?.scored_nodes ?? []);
  const nodes = new Map<string, { tone: string; tag: string | null; focus: boolean; scored: boolean; z: number }>();
  for (const n of graph.nodes) {
    const z = fresh?.node === n.id ? Math.abs(fresh.z) : (view.tick?.max_abs_z[n.id] ?? Number.NaN);
    let tone = "normal";
    let tag: string | null = null;
    if (z >= view.thresholds.wiggle_z) tone = "wiggle";
    if (symptoms.has(n.id) && roots.size) {
      tone = "symptom";
      tag = "symptom";
    }
    if (z >= view.thresholds.alarm_z) tone = "alarm";
    if (roots.has(n.id)) {
      tone = "root";
      tag = roots.get(n.id) ?? null;
    } else if (resolved.has(n.id) && tone !== "alarm") {
      tone = "resolved";
      tag = "resolved";
    }
    const focus = fNodes.has(n.id);
    if (focus && split.some((e) => e.startsWith(`b_${n.id}_`))) tag = "segment search";
    else if (focus) tag = tag ?? "checking";
    nodes.set(n.id, { tone, tag, focus, scored: scored.has(n.id) || fresh?.node === n.id, z });
  }
  const logs = new Map(graph.logs.map((l) => [l.id, fLogs.has(l.id)]));
  const edges = new Map<string, { focus: boolean; status: string | null }>();
  const factors = new Set(graph.edges.filter((e) => e.kind === "formula").flatMap((e) => e.sources));
  for (const e of graph.edges) {
    if (e.kind === "breakdown") continue;
    for (const s of e.sources) {
      const named = fEdges.has(e.id) && (fNodes.size <= 1 || fNodes.has(e.target) || fNodes.has(s) || fLogs.has(s));
      const ends = fNodes.has(e.target) && (fNodes.has(s) || fLogs.has(s));
      edges.set(`${e.id}:${s}`, { focus: named || ends, status: view.edges[e.id]?.status ?? e.status });
    }
  }
  for (const n of graph.nodes) {
    if (n.kind !== "ratio" || factors.has(n.id)) continue;
    for (const part of [n.numerator, n.denominator]) {
      if (part) edges.set(`def:${n.id}:${part}`, { focus: fNodes.has(n.id) && (fNodes.has(part) || fLogs.has(part)), status: null });
    }
  }
  return { nodes, logs, edges };
}

function expectSameAsGraphView(graph: Graph, view: RunView, model: SceneModel) {
  const oracle = graphViewOracle(graph, view);
  for (const node of model.nodes) {
    if (node.kind === "log") {
      expect(node.focus, node.id).toBe(oracle.logs.get(node.id));
      continue;
    }
    const want = oracle.nodes.get(node.id);
    expect(want, node.id).toBeDefined();
    expect({ id: node.id, tone: node.tone, tag: node.tag, focus: node.focus, scored: node.scored }).toEqual({
      id: node.id,
      tone: want?.tone,
      tag: want?.tag,
      focus: want?.focus,
      scored: want?.scored,
    });
    if (Number.isFinite(want?.z)) expect(node.z, node.id).toBe(want?.z);
    else expect(node.z, node.id).toBeNull();
  }
  expect(model.links.map((l) => l.id).sort()).toEqual([...oracle.edges.keys()].sort());
  for (const link of model.links) {
    const want = oracle.edges.get(link.id);
    expect({ id: link.id, focus: link.focus, status: link.status }).toEqual({ id: link.id, focus: want?.focus, status: want?.status });
  }
}

function replay(graph: Graph, events: ArgusEvent[], each?: (view: RunView, model: SceneModel, event: ArgusEvent) => void) {
  let view = emptyView("s", "replay");
  let model = sceneModel(graph, view);
  for (const event of events) {
    view = fold(view, event);
    model = sceneModel(graph, view, model);
    each?.(view, model, event);
  }
  return { view, model };
}

describe("the recorded S1 run", () => {
  const graph = loadGraph();
  const events = loadEvents();

  it("places all 27 metrics and 4 logs", () => {
    const model = sceneModel(graph, emptyView());
    expect(model.nodes.filter((n) => n.kind === "metric")).toHaveLength(27);
    expect(model.nodes.filter((n) => n.kind === "log")).toHaveLength(4);
    const spots = new Set(model.nodes.map((n) => n.position.join(",")));
    expect(spots.size).toBe(31);
    expect(model.phase).toBe("idle");
    expect(model.trace).toEqual([]);
    expect(model.added).toEqual([]);
  });

  it("shows the same state per metric, log and link as the 2D graph at every replay position", () => {
    let checked = 0;
    replay(graph, events, (view, model) => {
      expectSameAsGraphView(graph, view, model);
      checked += 1;
    });
    expect(checked).toBe(events.length);
  });

  it("cracks the payment success rate when the anomaly opens and marks it resolved at the end", () => {
    const tones: string[] = [];
    const { model } = replay(graph, events, (_, m) => {
      const tone = m.nodes.find((n) => n.id === "payment_success_rate")?.tone ?? "";
      if (tones[tones.length - 1] !== tone) tones.push(tone);
    });
    // small wiggles before the outage, then the alarm, the root cause and the resolution
    expect(tones.slice(0, 2)).toEqual(["normal", "wiggle"]);
    expect(tones.slice(tones.indexOf("alarm"))).toEqual(["alarm", "root", "resolved"]);
    expect(tones.slice(0, tones.indexOf("alarm")).every((t) => t === "normal" || t === "wiggle")).toBe(true);
    const psr = model.nodes.find((n) => n.id === "payment_success_rate");
    expect(psr?.tag).toBe("resolved");
  });

  it("walks the investigation phases in order", () => {
    const phases: string[] = [];
    replay(graph, events, (_, m) => {
      if (phases[phases.length - 1] !== m.phase) phases.push(m.phase);
    });
    expect(phases).toEqual(["idle", "anomaly", "investigating", "verdict", "resolved"]);
  });

  it("numbers the trace with the step numbers of the trail, in step order", () => {
    const { view, model } = replay(graph, events);
    const trail = view.steps.map((s) => s.step.step);
    const steps = model.trace.map((t) => t.step);
    expect(steps).toEqual([...steps].sort((a, b) => a - b));
    expect(new Set(steps)).toEqual(new Set(trail));
    expect(model.trace[0]).toEqual({ id: "payment_success_rate", step: 1 });
    // the walk reaches the calendar, the deploys and the provider status page
    const ids = new Set(model.trace.map((t) => t.id));
    for (const log of ["log_calendar", "log_deploys", "log_provider_status"]) expect(ids).toContain(log);
    for (const t of model.trace) expect(model.nodes.some((n) => n.id === t.id)).toBe(true);
  });

  it("counts ticks for the hourly pulse", () => {
    const { view, model } = replay(graph, events);
    expect(model.ticks).toBe(view.ticks);
    expect(model.ticks).toBe(events.filter((e) => e.type === "tick").length);
  });

  it("dims the logs the investigation ruled out", () => {
    const { view } = replay(graph, events);
    const out = ruledOut(view);
    expect(out.size).toBeGreaterThan(0);
    for (const id of out) expect(id.startsWith("log_")).toBe(true);
    expect(out.has("payment_success_rate")).toBe(false);
  });
});

describe("the other recorded scenarios", () => {
  it.each(["quiet", "s2", "s3", "s4"])("%s matches the 2D graph at every replay position", (scenario) => {
    const graph = loadGraph(scenario);
    replay(graph, loadEvents(scenario), (view, model) => expectSameAsGraphView(graph, view, model));
  });
});

describe("a graph that learns a metric", () => {
  const graph = loadGraph();
  const learned: Graph = {
    ...graph,
    version: graph.version + 1,
    nodes: [
      ...graph.nodes,
      { ...graph.nodes[0], id: "refund_rate", label: "Refund rate", description: "refunds per order", north_star: false },
    ],
    edges: [
      ...graph.edges,
      { ...graph.edges.find((e) => e.kind === "cause")!, id: "cause_refund_rate", target: "gmv", sources: ["refund_rate"] },
    ],
  };

  it("reports exactly the added metric once, and places it in a column of its own", () => {
    const view = emptyView();
    const v1 = sceneModel(graph, view);
    const v2 = sceneModel(learned, view, v1);
    expect(v2.added).toEqual(["refund_rate"]);
    expect(sceneModel(learned, view, v2).added).toEqual([]);
    const x = (m: SceneModel, id: string) => m.nodes.find((n) => n.id === id)?.position[0] ?? Number.NaN;
    const rightmost = Math.max(...v1.nodes.map((n) => n.position[0]));
    expect(x(v2, "refund_rate")).toBeGreaterThan(rightmost);
    expect(v2.links.some((l) => l.source === "refund_rate" && l.target === "gmv" && l.kind === "cause")).toBe(true);
  });

  it("reports nothing on the first model", () => {
    expect(sceneModel(learned, emptyView()).added).toEqual([]);
  });
});

describe("node titles", () => {
  const graph = loadGraph();
  it("say what the 2D graph says on hover", () => {
    const gmv = graph.nodes.find((n) => n.id === "gmv")!;
    expect(nodeTitle(graph, { id: "gmv", kind: "metric", scored: true })).toBe(`${gmv.label}: ${gmv.description}`);
    expect(nodeTitle(graph, { id: "gmv", kind: "metric", scored: false })).toContain("(scored when an investigation needs it)");
    expect(nodeTitle(graph, { id: "log_deploys", kind: "log", scored: false })).toBe("log of state changes (evidence source)");
  });
});
