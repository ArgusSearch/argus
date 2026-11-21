// Shaping the recorded bench scorecard (web/src/views/fixtures/scorecard.sample.json) for the table.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { foldLabels, isScorecard, misses, scenarioLines, summaryMetrics, type Scorecard } from "../../src/views/scorecard";

const card: Scorecard = JSON.parse(readFileSync(fileURLToPath(new URL("../../src/views/fixtures/scorecard.sample.json", import.meta.url)), "utf8"));

describe("scorecard", () => {
  it("recognises a scorecard and rejects anything else", () => {
    expect(isScorecard(card)).toBe(true);
    expect(isScorecard({ detail: "not built yet" })).toBe(false);
    expect(isScorecard(null)).toBe(false);
  });

  it("has one line per scenario with a cell per agent", () => {
    const lines = scenarioLines(card);
    expect(lines.map((l) => l.scenario)).toEqual(card.scenarios);
    for (const line of lines) for (const agent of card.agents) expect(line.cells[agent]?.row.scenario).toBe(line.scenario);
  });

  it("colors a cell by its runs: all passed green, none red", () => {
    for (const line of scenarioLines(card)) {
      for (const cell of Object.values(line.cells)) {
        if (!cell) continue;
        const { passed, runs } = cell.row;
        expect(cell.tone).toBe(passed === runs ? "good" : passed === 0 ? "bad" : "warn");
        expect(cell.passLabel).toBe(`${passed}/${runs}`);
      }
    }
  });

  it("keeps every miss visible", () => {
    const argus = misses(card, "argus");
    expect(argus).toEqual(card.rows.filter((r) => r.agent === "argus" && r.passed < r.runs));
    expect(argus.length).toBeGreaterThan(0);
  });

  it("labels the headline measures from the bench's own numbers", () => {
    const s = card.summaries.find((x) => x.agent === "argus");
    if (!s) throw new Error("no argus summary");
    const m = Object.fromEntries(summaryMetrics(s).map((x) => [x.key, x]));
    expect(m.recall.value).toBe(s.recall === null ? "–" : `${Math.round(s.recall * 100)}%`);
    expect(m.fa.value).toBe(String(s.false_alarms));
    expect(m.fa.tone).toBe(s.false_alarms === 0 ? "good" : "bad");
  });

  it("folds repeated verdict labels in seed order", () => {
    expect(foldLabels(["exact", "exact", "silent", "exact"])).toEqual([
      ["exact", 2],
      ["silent", 1],
      ["exact", 1],
    ]);
    expect(foldLabels([])).toEqual([]);
  });
});
