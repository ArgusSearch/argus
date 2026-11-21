// The investigation story and the demo beats, folded from the recorded S1 run (fixtures/events.jsonl).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { emptyView, foldAll } from "../../src/lib/store";
import type { ArgusEvent, Graph } from "../../src/lib/types";
import { autonomyCounts } from "../../src/views/autonomy";
import { beatFor, decidedIncidents, demoOptions, investigationStarted, withoutDemo } from "../../src/views/demo/demo";
import { breadcrumb, chapters, scopeLabel, stepQuestion, suspects, verdictOf } from "../../src/views/investigation";
import { investigations, metricStatus } from "../../src/views/model";

const read = (path: string) => readFileSync(fileURLToPath(new URL(path, import.meta.url)), "utf8");
const events: ArgusEvent[] = read("../../../fixtures/events.jsonl")
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line));
const graph: Graph = JSON.parse(read("../../../fixtures/graph.json"));
const full = foldAll(emptyView("s", "replay"), events);
const upTo = (pred: (e: ArgusEvent) => boolean) => foldAll(emptyView("s", "replay"), events.slice(0, events.findIndex(pred) + 1));

describe("investigation story", () => {
  const steps = full.steps.filter((s) => s.anomalyId === "an_0001");
  const trail = steps.map((s) => s.step);

  it("links the walk to the incident filed after it", () => {
    const list = investigations(full);
    expect(list).toHaveLength(1);
    expect(list[0]).toMatchObject({ anomalyId: "an_0001", node: "payment_success_rate", incidentId: "INC-0001" });
  });

  it("reads the root-cause path in the order the search added each dimension", () => {
    const { node, crumbs } = breadcrumb(trail, "payment_success_rate");
    expect(node).toBe("payment_success_rate");
    expect(crumbs).toEqual([
      { dim: "platform", value: "android" },
      { dim: "country", value: "DE" },
      { dim: "provider", value: "PayCo" },
    ]);
  });

  it("strikes the Android release by its holdout and keeps PayCo", () => {
    const s = suspects(steps);
    const byRef = Object.fromEntries(s.map((x) => [x.ref, x]));
    expect(byRef["ps_payco_degraded"]?.kept).toBe(true);
    const release = byRef["dep_android-app_8.3.0"];
    expect(release?.kept).toBe(false);
    expect(release?.reason).toContain("holdout");
    expect(scopeLabel(release?.scope ?? {})).toBe("platform android");
    for (const x of s.filter((x) => !x.kept)) expect(x.reason.length).toBeGreaterThan(0);
    expect(scopeLabel({})).toBe("everyone");
  });

  it("groups the steps into chapters in playbook order and names each step's question", () => {
    expect(chapters(steps).map((c) => c.chapter)).toEqual(["data", "plan", "where", "why", "cost", "verdict"]);
    expect(stepQuestion(trail[0])).toBe("Is the data complete?");
    expect(trail.map(stepQuestion)).toContain("When did it start?");
    expect(trail.map(stepQuestion)).toContain("How much money is it?");
    expect(verdictOf(trail)).toBe("SUPPORTED_CAUSE");
  });

  it("is empty before the first step", () => {
    const before = upTo((e) => e.type === "anomaly_opened");
    expect(investigations(before)).toHaveLength(0);
    expect(breadcrumb([], null).crumbs).toEqual([]);
  });
});

describe("demo beats", () => {
  it("walks through the S1 story and never states a measurement (money, shares, scores)", () => {
    const ids = new Set<string>();
    let view = emptyView("s", "replay");
    for (const e of events) {
      view = foldAll(view, [e]);
      const beat = beatFor(view, graph);
      ids.add(beat.id);
      // a suspect's own description (data from the event log) may carry numbers; the caption adds none
      const own = beat.id === "suspects" ? beat.text.replace(/: .*\. The rest/, ": . The rest") : beat.text;
      expect(own).not.toMatch(/€|EUR|%|\bz [-+]?\d/);
    }
    for (const id of ["watching", "anomaly", "checks", "localised", "suspects", "verdict", "monitoring", "resolved"]) expect(ids.has(id)).toBe(true);
  });

  it("ends on the resolved incident", () => {
    expect(beatFor(full, graph).id).toBe("resolved");
    expect(investigationStarted(full)).toBe(true);
    expect(decidedIncidents(full)).toEqual(["INC-0001"]);
  });

  it("reads its options from the URL with safe defaults", () => {
    expect(demoOptions("")).toEqual({ demo: false, speed: 2, captions: false, hold: 12, endOnReport: false });
    expect(demoOptions("?demo=1&speed=8&captions=1&hold=20&end=report")).toEqual({ demo: true, speed: 8, captions: true, hold: 20, endOnReport: true });
    expect(demoOptions("?demo=1&speed=3&hold=1").speed).toBe(2);
    expect(demoOptions("?demo=1&hold=1").hold).toBe(12);
    expect(withoutDemo("http://127.0.0.1:8000/?demo=1&speed=4&captions=1&view=tree#x")).toBe("/?view=tree#x");
    expect(withoutDemo("http://127.0.0.1:8000/?demo=1")).toBe("/");
  });
});

describe("autonomy counts and metric state", () => {
  it("counts what the reducer folded, with zero human actions", () => {
    const counts = Object.fromEntries(autonomyCounts(full).map((c) => [c.key, c.value]));
    expect(counts.hours).toBe(full.ticks);
    expect(counts.edges).toBe(full.edgeChanges.length);
    expect(counts.anomalies).toBe(1);
    expect(counts.investigations).toBe(1);
    expect(counts.incidents).toBe(1);
    expect(counts.human).toBe(0);
  });

  it("marks the root while the incident is open and resolved after", () => {
    const open = upTo((e) => e.type === "incident_updated");
    expect(metricStatus(open, "payment_success_rate").state).toMatch(/root|checking/);
    expect(metricStatus(full, "payment_success_rate").state).toBe("resolved");
    expect(metricStatus(full, "gmv").state).not.toBe("root");
  });
});
