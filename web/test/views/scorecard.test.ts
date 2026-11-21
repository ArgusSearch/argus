// Shaping the recorded bench scorecard (web/src/views/fixtures/scorecard.sample.json) for the table.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import {
  AGENT_TEXT,
  foldLabels,
  headlineRows,
  isScorecard,
  misses,
  orderedSummaries,
  SCENARIO_TEXT,
  scenarioLines,
  summaryMetrics,
  type Scorecard,
} from "../../src/views/scorecard";

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
    for (const agent of card.agents) expect(misses(card, agent)).toEqual(card.rows.filter((r) => r.agent === agent && r.passed < r.runs));
    expect(card.agents.some((a) => misses(card, a).length > 0)).toBe(true);
  });

  // The dashboard and the scorecard view fall back to this sample while GET /bench/results is a stub, so it must be
  // the current bench (`uv run argus-bench run --agents argus,argus-stage1,threshold`), not an older recording.
  it("is a recording of the current bench: every scenario, full Argus, its Stage-1 fallback and the baseline", () => {
    expect(card.scenarios).toEqual(["quiet", "s1", "s2", "s3", "s4", "s5"]);
    expect(card.agents).toEqual(["argus", "argus-stage1", "threshold"]);
    for (const s of card.scenarios) expect(SCENARIO_TEXT[s]).toBeDefined();
    for (const a of card.agents) expect(AGENT_TEXT[a]).toBeDefined();
    const argus = card.summaries.find((x) => x.agent === "argus");
    expect(argus).toMatchObject({ runs: 18, pass_at_1: 1, recall: 1, cause_accuracy: 1, false_alarms: 0, all_verified: true });
    expect(misses(card, "argus")).toEqual([]);
  });

  it("reads Argus first, then its references", () => {
    expect(orderedSummaries(card).map((s) => s.agent)).toEqual(["argus", "argus-stage1", "threshold"]);
    const shuffled = { ...card, summaries: [...card.summaries].reverse() };
    expect(orderedSummaries(shuffled).map((s) => s.agent)).toEqual(["argus", "argus-stage1", "threshold"]);
  });

  it("colors only Argus on the dashboard: a reference's miss is never styled as Argus's", () => {
    const rows = headlineRows(card, ["recall", "cause", "ttd", "fa"]);
    expect(rows.map((r) => r.key)).toEqual(["recall", "cause", "ttd", "fa"]);
    for (const r of rows) {
      expect(r.cells.map((c) => c.agent)).toEqual(["argus", "argus-stage1", "threshold"]);
      for (const c of r.cells.slice(1)) expect(c.tone).toBe("neutral");
    }
    const cause = rows.find((r) => r.key === "cause");
    expect(cause?.cells[0]).toEqual({ agent: "argus", value: "100%", tone: "good" });

    // An Argus miss still shows in red: the dashboard mutes the references, not Argus's own failures.
    const worse = { ...card, summaries: card.summaries.map((s) => (s.agent === "argus" ? { ...s, cause_accuracy: 0.5 } : s)) };
    expect(headlineRows(worse, ["cause"])[0].cells[0]).toEqual({ agent: "argus", value: "50%", tone: "bad" });
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
