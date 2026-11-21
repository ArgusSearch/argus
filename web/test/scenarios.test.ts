// Folds every recorded scenario (fixtures/<scenario>/events.jsonl, written by `make fixtures`) through the
// reducer the page uses: each world's story must reach the page, and a quiet world must stay quiet.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { impactNoun } from "../src/lib/format";
import { emptyView, foldAll, type RunView } from "../src/lib/store";
import type { ArgusEvent, Graph } from "../src/lib/types";

const graph: Graph = JSON.parse(readFileSync(fileURLToPath(new URL("../../fixtures/s4/graph.json", import.meta.url)), "utf8"));

function replay(scenario: string): { events: ArgusEvent[]; view: RunView } {
  const path = fileURLToPath(new URL(`../../fixtures/${scenario}/events.jsonl`, import.meta.url));
  const events: ArgusEvent[] = readFileSync(path, "utf8")
    .split("\n")
    .filter(Boolean)
    .map((line) => JSON.parse(line));
  return { events, view: foldAll(emptyView("s", "replay"), events) };
}

const noteKinds = (view: RunView) => view.feed.flatMap((item) => (item.kind === "note" ? [item.note.kind] : []));

describe.each(["quiet", "s2", "s3", "s4"])("%s replay", (scenario) => {
  const { events, view } = replay(scenario);

  it("folds every tick and the first edge tests", () => {
    expect(view.ticks).toBe(events.filter((e) => e.type === "tick").length);
    expect(view.ticks).toBeGreaterThan(0);
    expect(view.feed.filter((item) => item.kind === "edges")).toHaveLength(1);
    expect(view.lastSeq).toBe(events[events.length - 1].seq);
  });
});

describe("the quiet world", () => {
  const { view } = replay("quiet");

  it("opens nothing and wakes nobody", () => {
    expect(view.anomalies).toHaveLength(0);
    expect(Object.keys(view.incidents)).toHaveLength(0);
    expect(noteKinds(view)).toEqual([]);
    expect(view.alarms).toBe(0);
  });
});

describe("S2 planned budget increase", () => {
  const { view } = replay("s2");

  it("investigates the spend rise and logs it as expected without paging", () => {
    expect(view.anomalies.map((a) => a.node)).toEqual(["ad_spend"]);
    expect(view.steps.length).toBeGreaterThan(0);
    expect(Object.keys(view.incidents)).toHaveLength(0);
    expect(noteKinds(view)).toEqual(["expected"]);
  });
});

describe("S3 orders loader stall", () => {
  const { view } = replay("s3");

  it("raises a data issue instead of a business incident", () => {
    expect(view.anomalies).toHaveLength(0);
    expect(Object.keys(view.incidents)).toHaveLength(0);
    expect(noteKinds(view)).toEqual(["data_issue"]);
    expect(view.notes[0].reason).toContain("fact_orders_hourly");
  });
});

describe("S4 pacer overburn", () => {
  const { events, view } = replay("s4");

  it("pages one incident with its supported cause", () => {
    const incidents = Object.values(view.incidents);
    expect(incidents).toHaveLength(1);
    expect(incidents[0].verdict).toBe("SUPPORTED_CAUSE");
    expect(incidents[0].root_node).toBe("pacing_ratio");
    expect(view.feed.filter((item) => item.kind === "incident")).toHaveLength(1);
  });

  it("walks the graph to the pacer rollout", () => {
    expect(view.steps.map((s) => s.step.kind)).toContain("verdict");
    const verdict = events.findIndex((e) => e.type === "investigation_step" && e.payload.step.kind === "verdict");
    const atVerdict = foldAll(emptyView(), events.slice(0, verdict + 1));
    expect(atVerdict.focus?.nodes).toEqual(["ad_spend"]);
    expect(atVerdict.focus?.logs).toEqual(expect.arrayContaining(["log_deploys"]));
  });
});

describe("what an incident's euros count", () => {
  it("names lost orders GMV and a pacer overburn extra ad spend", () => {
    expect(impactNoun("payment_success_rate", "down", graph)).toBe("GMV lost");
    expect(impactNoun("orders", "down", graph)).toBe("GMV lost");
    expect(impactNoun("gmv", "up", graph)).toBe("extra GMV");
    expect(impactNoun("pacing_ratio", "up", graph)).toBe("extra ad spend");
    expect(impactNoun("ad_spend", "down", graph)).toBe("ad spend short");
    expect(impactNoun("roas", "down", graph)).toBe("attributed GMV short");
  });

  it("falls back to GMV before the graph has loaded", () => {
    expect(impactNoun("pacing_ratio", "down", null)).toBe("GMV lost");
  });
});
