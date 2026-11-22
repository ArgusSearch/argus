// The graph bar's "checking <metric>" label is shown while an investigation runs, not after its verdict (#13).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { checkingNode, emptyView, foldAll } from "../src/lib/store";
import type { ArgusEvent } from "../src/lib/types";

const fixtures = fileURLToPath(new URL("../../fixtures/events.jsonl", import.meta.url));
const events: ArgusEvent[] = readFileSync(fixtures, "utf8")
  .split("\n")
  .filter(Boolean)
  .map((line) => JSON.parse(line) as ArgusEvent);

const upTo = (pred: (e: ArgusEvent) => boolean) => foldAll(emptyView(), events.slice(0, events.findIndex(pred) + 1));
const isVerdict = (e: ArgusEvent) => e.type === "investigation_step" && e.payload.step.kind === "verdict";

describe("checkingNode", () => {
  it("is empty before any anomaly", () => {
    expect(checkingNode(upTo((e) => e.type === "tick"))).toBeNull();
  });

  it("names the anomalous metric while the investigation runs", () => {
    const view = upTo((e) => e.type === "investigation_step");
    expect(checkingNode(view)).toBe(view.anomalies[0].node);
  });

  it("is empty once the verdict step arrives, although the graph keeps its focus for the hour", () => {
    const view = upTo(isVerdict);
    expect(view.focus).not.toBeNull();
    expect(checkingNode(view)).toBeNull();
  });
});
