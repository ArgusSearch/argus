// Folds the recorded S1 run (fixtures/events.jsonl) through the same reducer the page uses.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { emptyView, fold, foldAll, focusOf, recount } from "../src/lib/store";
import type { ArgusEvent, TrailStep } from "../src/lib/types";

const fixtures = fileURLToPath(new URL("../../fixtures/events.jsonl", import.meta.url));
const events: ArgusEvent[] = readFileSync(fixtures, "utf8")
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line));

describe("fold", () => {
  const view = foldAll(emptyView("s", "replay"), events);

  it("counts what the watcher scored", () => {
    const ticks = events.filter((e) => e.type === "tick");
    expect(view.ticks).toBe(ticks.length);
    expect(view.scoredSeries).toBe(ticks.reduce((n, e) => n + (e.type === "tick" ? e.payload.scored_nodes.length : 0), 0));
    expect(view.wiggles + view.alarms).toBeGreaterThan(0);
    expect(view.anomalies).toHaveLength(1);
  });

  it("recounts exactly under other thresholds", () => {
    const strict = recount(view.zBuckets, { alarm_z: 50, pair_z: 50, wiggle_z: 50 });
    expect(strict).toEqual({ wiggles: 0, alarms: 0 });
    const all = recount(view.zBuckets, { alarm_z: 0, pair_z: 0, wiggle_z: 0 });
    expect(all.alarms).toBe(view.scoredSeries);
  });

  it("tracks the incident to resolution", () => {
    const inc = view.incidents["INC-0001"];
    expect(inc.state).toBe("resolved");
    expect(inc.verdict).toBe("SUPPORTED_CAUSE");
    expect(view.feed.filter((i) => i.kind === "incident")).toHaveLength(1);
  });

  it("walks the graph while it investigates", () => {
    expect(view.steps.map((s) => s.step.kind)).toContain("verdict");
    const upTo = (kind: string) => {
      const i = events.findIndex((e) => e.type === "investigation_step" && e.payload.step.kind === kind);
      return foldAll(emptyView(), events.slice(0, i + 1));
    };
    expect(upTo("freshness").focus?.nodes).toEqual(["payment_success_rate"]);
    expect(upTo("segment").focus?.edges).toEqual(
      expect.arrayContaining(["b_payment_success_rate_country", "b_payment_success_rate_platform"]),
    );
    expect(upTo("events").focus?.logs).toEqual(expect.arrayContaining(["log_deploys", "log_provider_status"]));
    expect(upTo("verdict").focus?.logs).toEqual(["log_provider_status"]);
  });

  it("prefers a step's own focus", () => {
    const step = { kind: "segment", data: { focus: { nodes: ["x"], logs: [], edges: ["e"] } } } as unknown as TrailStep;
    expect(focusOf(step, "payment_success_rate")).toEqual({ nodes: ["x"], edges: ["e"], logs: [] });
  });

  it("groups first edge tests into one graph-change card", () => {
    const cards = view.feed.filter((i) => i.kind === "edges");
    expect(cards).toHaveLength(1);
    expect(cards[0].kind === "edges" && cards[0].changes.every((c) => c.from === null)).toBe(true);
  });

  it("ignores events it has already seen", () => {
    expect(fold(view, events[3])).toBe(view);
  });
});

describe("the walk", () => {
  it("stays on screen through its own tick and ends with the next hour", () => {
    const verdict = events.findIndex((e) => e.type === "investigation_step" && e.payload.step.kind === "verdict");
    const closing = events.findIndex((e, i) => i > verdict && e.type === "tick");
    expect(foldAll(emptyView(), events.slice(0, closing + 1)).focus?.logs).toEqual(["log_provider_status"]);
    const next = events.findIndex((e, i) => i > closing && e.type === "tick");
    expect(foldAll(emptyView(), events.slice(0, next + 1)).focus).toBeNull();
  });
});
