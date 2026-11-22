import { readFileSync } from "node:fs";
import { expect, it } from "vitest";
import { emptyView, foldAll } from "../../src/lib/store";
import type { ArgusEvent, Graph } from "../../src/lib/types";
import { calendarEntries, weekOf } from "../../src/settings/model";

it("puts the S2 plan and its held alert in their calendar lanes with receipt evidence", () => {
  const read = (name: string) => readFileSync(new URL(`../../../fixtures/s2/${name}`, import.meta.url), "utf8");
  const graph: Graph = JSON.parse(read("graph.json"));
  const events = read("events.jsonl")
    .trim()
    .split("\n")
    .map((line) => JSON.parse(line) as ArgusEvent);

  const entries = calendarEntries(foldAll(emptyView("s2", "replay"), events), graph);
  const planned = entries.find((entry) => entry.id === "plan:cal_adv_01_FR_push");
  expect(planned).toMatchObject({
    lane: "plan",
    ts: "2026-11-20T07:00:00",
    tone: "ok",
    plan: { uplift: 0.41, delivered: 0.4775, status: "as planned", note: { kind: "expected" } },
  });
  expect(planned?.receipts).toContain("r176");
  expect(entries).toContainEqual(expect.objectContaining({ lane: "skeptic", id: "note:note_0001" }));
  expect(weekOf("2026-11-20T07:00:00")[0]).toBe("2026-11-16");
});
