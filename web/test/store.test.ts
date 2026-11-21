// Folds the bundled S1 recording through the same reducer the page uses.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { emptyView, fold, foldAll } from "../src/lib/store";
import type { ArgusEvent } from "../src/lib/types";

const recording = fileURLToPath(new URL("../../src/argus/api/recordings/s1/events.jsonl", import.meta.url));
const events: ArgusEvent[] = readFileSync(recording, "utf8")
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line));

describe("fold", () => {
  const view = foldAll(emptyView("s", "replay"), events);

  it("counts the funnel", () => {
    const ticks = events.filter((e) => e.type === "tick").length;
    expect(view.ticks).toBe(ticks);
    expect(view.scoredSeries).toBeGreaterThan(ticks * 20);
    expect(view.wiggles).toBeGreaterThan(0);
    expect(view.anomalies).toHaveLength(1);
  });

  it("tracks the incident to resolution", () => {
    const inc = view.incidents["INC-0001"];
    expect(inc.state).toBe("resolved");
    expect(inc.verdict).toBe("SUPPORTED_CAUSE");
    expect(inc.severity_eur).toBeGreaterThan(0);
    expect(view.feed.filter((i) => i.kind === "incident")).toHaveLength(1);
  });

  it("keeps the trail and the walk", () => {
    expect(view.steps.map((s) => s.step.kind)).toContain("verdict");
    const mid = foldAll(emptyView(), events.slice(0, events.findIndex((e) => e.type === "investigation_step") + 1));
    expect(mid.focus?.nodes.length).toBeGreaterThan(0);
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
