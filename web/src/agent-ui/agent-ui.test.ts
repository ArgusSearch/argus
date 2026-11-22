import { describe, expect, it } from "vitest";
import type { ActivityRecord, AskAnswer, ProposalView, RunSummary } from "../lib/agent";
import {
  evidenceChecks,
  firstSentence,
  gateOf,
  groupRuns,
  groupSummary,
  isLive,
  liveLine,
  outcomeTone,
  pendingProposals,
  proposalsOf,
  stepsOf,
  titleWithCount,
} from "./activity";
import { formatElapsed, RunClock } from "./clock";
import { atEnd, FOLLOWING, initialTail, jumpLabel, releases, tailReducer, transition, unseen, type Tail, type TailEvent } from "./follow";
import { caretOnEdge, remember, step, type HistoryPosition } from "./history";
import s4Activity from "../../../fixtures/agent/v1/s4/activity.jsonl?raw";
import s4Ask from "../../../fixtures/agent/v1/s4/ask.jsonl?raw";

// the recorded agent run the demo plays (scenario s4): 16 records of run_0001, three checks, one proposal
const S4: ActivityRecord[] = s4Activity
  .trim()
  .split("\n")
  .map((l: string) => JSON.parse(l) as ActivityRecord);
const S4_ASK = JSON.parse(s4Ask.trim().split("\n")[0]).response as AskAnswer;

let seq = 1000;
function rec(kind: ActivityRecord["kind"], patch: Partial<ActivityRecord> = {}): ActivityRecord {
  seq += 1;
  return {
    seq,
    run_id: "run_x",
    sim_ts: "2026-11-20T02:00:00",
    kind,
    stage: "",
    actor: "host",
    text: "",
    anomaly_id: null,
    incident_id: null,
    action_id: null,
    tool: null,
    args: null,
    observation: null,
    receipt_links: [],
    model: null,
    input_tokens: null,
    output_tokens: null,
    usd: null,
    gate_action: null,
    ...patch,
  };
}

function result(tool: string, outcome: string, patch: Partial<ActivityRecord> = {}): ActivityRecord {
  return rec("tool_result", {
    tool,
    observation: {
      call_id: `${tool}:1`,
      tool,
      args: {},
      hypothesis: null,
      prediction: null,
      expect: null,
      outcome,
      summary: `${tool} said ${outcome}`,
      data: {},
      fact_handles: [],
      receipt_refs: [],
      availability: "ok",
    },
    ...patch,
  });
}

const run = (id: string, status: RunSummary["status"], kind: RunSummary["kind"] = "investigate"): RunSummary => ({
  run_id: id,
  kind,
  mode: "replay",
  sim_ts: "2026-11-20T02:00:00",
  anomaly_id: null,
  incident_id: null,
  status,
  stop_reason: null,
  llm_calls: 4,
  tool_calls: 3,
  input_tokens: 0,
  output_tokens: 0,
  usd: 0.045867,
  gate: null,
  fallback: null,
});

const proposal = (id: string, state: ProposalView["state"], run_id = "run_0001"): ProposalView =>
  ({ id, state, run_id, digest: "d", incident_ref: "INC-0001", action: "roll back" }) as ProposalView;

describe("grouping the activity into runs", () => {
  it("folds the recorded s4 run into one group with each check paired to its result", () => {
    const groups = groupRuns(S4, [run("run_0001", "done")]);
    expect(groups).toHaveLength(1);
    const g = groups[0];
    expect(g.key).toBe("run_0001");
    expect(g.kind).toBe("investigate");
    expect(g.finished).toBe(true);
    expect(g.checks.map((c) => [c.tool, c.call?.seq, c.result?.seq])).toEqual([
      ["list_events", 3, 4],
      ["holdout_check", 6, 7],
      ["placebo_test", 9, 10],
    ]);
    // 16 records, three pairs fold into three rows
    expect(g.steps).toHaveLength(13);
    expect(g.proposed).toEqual(["act_0001"]);
    expect(g.roles).toEqual(["detective", "skeptic", "operator"]);
  });

  it("reads a finished run as one summary line with its outcomes and the gate's verdict", () => {
    const g = groupRuns(S4)[0];
    expect(groupSummary(g)).toBe("Ran 3 checks: 1 found, 1 consistent, 1 unusual");
    expect(gateOf(g)).toEqual({ claimed: "SUPPORTED_CAUSE", admitted: "SUPPORTED_CAUSE" });
  });

  it("keeps runs apart in the order they first appeared, and gathers records outside a run as quiet hours", () => {
    const records = [
      rec("watch", { run_id: null }),
      rec("watch", { run_id: null }),
      rec("run_started", { run_id: "a" }),
      rec("run_started", { run_id: "b" }),
      rec("tool_call", { run_id: "a", tool: "holdout_check" }),
      rec("watch", { run_id: null }),
    ];
    const groups = groupRuns(records);
    expect(groups.map((g) => [g.key.replace(/\d+$/, "#"), g.records.length])).toEqual([
      ["quiet:#", 2],
      ["a", 2],
      ["b", 1],
      ["quiet:#", 1],
    ]);
    expect(groupSummary(groups[0])).toBe("Watched 2 quiet hours, no model call");
  });

  it("pairs a result with the oldest open call of the same check, and keeps a result without a call", () => {
    const steps = stepsOf([
      rec("tool_call", { tool: "placebo_test" }),
      rec("tool_call", { tool: "placebo_test" }),
      result("placebo_test", "unusual"),
      result("holdout_check", "consistent"),
    ]);
    expect(steps.map((s) => (s.kind === "check" ? [s.tool, !!s.call, !!s.result] : s.kind))).toEqual([
      ["placebo_test", true, true],
      ["placebo_test", true, false],
      ["holdout_check", false, true],
    ]);
  });

  it("is live until run_finished arrives, while the API says running or a presentation streams", () => {
    const open = groupRuns([rec("run_started", { run_id: "r" })], [run("r", "done")])[0];
    expect(isLive(open)).toBe(false);
    expect(isLive(open, true)).toBe(true);
    expect(isLive(groupRuns([rec("run_started", { run_id: "r" })], [run("r", "running")])[0])).toBe(true);
    expect(isLive(groupRuns(S4, [run("run_0001", "running")])[0], true)).toBe(false);
  });

  it("says what a live run is doing now: the running check, else the first sentence of the newest thought", () => {
    const thinking = groupRuns([rec("run_started"), rec("thought", { text: "Spend tripled. I suspect a budget change." })])[0];
    expect(liveLine(thinking)).toMatchObject({ verb: "Thinks", text: "Spend tripled." });
    const checking = groupRuns([
      rec("run_started"),
      rec("tool_call", {
        tool: "holdout_check",
        observation: { hypothesis: "Pacing is normal outside DE/FR. More words." } as ActivityRecord["observation"],
      }),
    ])[0];
    expect(liveLine(checking)).toMatchObject({ verb: "Runs holdout_check", role: "skeptic", text: "Pacing is normal outside DE/FR." });
    expect(groupSummary(checking, true)).toBe("Running 1 check");
  });

  it("takes the first sentence the way T3 Code's live thought line does", () => {
    expect(firstSentence("**Checking pacing**\nthen more")).toBe("Checking pacing");
    expect(firstSentence("Use `holdout_check` on [DE](x). Then more.")).toBe("Use holdout_check on DE.");
    expect(firstSentence("no end mark")).toBe("no end mark");
  });

  it("tones outcomes: backing ones ok, ruling-out ones alarm", () => {
    expect(["confirmed", "consistent", "unusual", "found"].map(outcomeTone)).toEqual(["ok", "ok", "ok", "ok"]);
    expect(["refuted", "ruled_out", "not_found"].map(outcomeTone)).toEqual(["alarm", "alarm", "alarm"]);
    expect(outcomeTone("inconclusive")).toBe("muted");
  });
});

describe("approval counters", () => {
  const proposals = [proposal("act_0001", "AWAIT_OPERATOR"), proposal("act_0002", "APPLIED"), proposal("act_0003", "AWAIT_OPERATOR", "run_0002")];

  it("counts only proposals waiting for a person", () => {
    expect(pendingProposals(proposals).map((p) => p.id)).toEqual(["act_0001", "act_0003"]);
    expect(pendingProposals([])).toEqual([]);
  });

  it("finds a run's proposals by the ids its records name", () => {
    expect(proposalsOf(groupRuns(S4)[0], proposals).map((p) => p.id)).toEqual(["act_0001"]);
  });

  it("puts the waiting count in front of the tab title, once, and takes it away at zero", () => {
    expect(titleWithCount("Argus · Mission Control", 1)).toBe("(1) Argus · Mission Control");
    expect(titleWithCount("(1) Argus · Mission Control", 2)).toBe("(2) Argus · Mission Control");
    expect(titleWithCount("(2) Argus · Mission Control", 0)).toBe("Argus · Mission Control");
  });
});

describe("the checks behind an Ask answer", () => {
  it("finds the checks whose receipts the recorded answer cites", () => {
    expect(evidenceChecks(S4_ASK, S4).map((c) => c.tool)).toEqual(["list_events", "holdout_check"]);
  });

  it("takes every finished check of the answer's own run", () => {
    const records = [result("holdout_check", "consistent", { run_id: "ask_1" }), result("placebo_test", "unusual", { run_id: "other" })];
    expect(evidenceChecks({ run_id: "ask_1", receipt_links: [], claims: [] }, records).map((c) => c.tool)).toEqual(["holdout_check"]);
    expect(evidenceChecks({ run_id: null, receipt_links: [], claims: [] }, records)).toEqual([]);
  });
});

describe("follow-tail", () => {
  const run = (events: TailEvent[], from: Tail = initialTail(3)) => events.reduce(tailReducer, from);

  it("follows from the start and counts nothing as new while following", () => {
    const t = run([{ type: "count", count: 5 }]);
    expect(t.follow).toBe(FOLLOWING);
    expect(unseen(t)).toBe(0);
  });

  it("lets go when the reader moves away, and counts what arrives meanwhile", () => {
    const t = run([{ type: "navigated" }, { type: "leftEnd" }, { type: "count", count: 4 }, { type: "count", count: 6 }]);
    expect(t.follow).toEqual({ mode: "released", atEnd: false });
    expect(unseen(t)).toBe(3);
    expect(jumpLabel(unseen(t))).toBe("Jump to latest (3 new)");
  });

  it("follows again when the reader scrolls back to the end or jumps", () => {
    const away = run([{ type: "navigated" }, { type: "leftEnd" }, { type: "count", count: 5 }]);
    expect(run([{ type: "reachedEnd" }], away).follow).toBe(FOLLOWING);
    const jumped = run([{ type: "followEnd" }], away);
    expect(jumped.follow).toBe(FOLLOWING);
    expect(unseen(jumped)).toBe(0);
  });

  it("does not re-arm from a scroll key pressed at the end (T3 Code's rule)", () => {
    const s = transition(FOLLOWING, "navigated");
    expect(s).toEqual({ mode: "released", atEnd: true });
    expect(transition(s, "reachedEnd")).toBe(s);
    expect(transition(transition(s, "leftEnd"), "reachedEnd")).toBe(FOLLOWING);
  });

  it("ignores the one-frame leave of the end that growth causes while following", () => {
    expect(transition(FOLLOWING, "leftEnd")).toBe(FOLLOWING);
  });

  it("sees a list that starts over (a new stream) as read", () => {
    const t = run([{ type: "navigated" }, { type: "leftEnd" }, { type: "count", count: 8 }, { type: "count", count: 2 }]);
    expect(unseen(t)).toBe(0);
  });

  it("lets only reader input that can leave the end release it", () => {
    const top = { canScrollUp: false, awayFromEnd: true };
    const end = { canScrollUp: true, awayFromEnd: false };
    expect(releases({ source: "wheel", up: true }, end)).toBe(true);
    expect(releases({ source: "wheel", up: true }, top)).toBe(false);
    expect(releases({ source: "wheel", up: false }, end)).toBe(false);
    expect(releases({ source: "key", up: false }, end)).toBe(false);
    expect(releases({ source: "pointer", onScrollbar: false }, end)).toBe(false);
    expect(releases({ source: "pointer", onScrollbar: true }, end)).toBe(true);
    expect(releases({ source: "touch", up: true }, end)).toBe(true);
    expect(releases({ source: "touch", up: false }, end)).toBe(false);
    expect(releases({ source: "touch", up: true }, top)).toBe(false);
  });

  it("counts the last 40 px as the end", () => {
    expect(atEnd({ scrollHeight: 1000, clientHeight: 500, scrollTop: 460 })).toBe(true);
    expect(atEnd({ scrollHeight: 1000, clientHeight: 500, scrollTop: 459 })).toBe(false);
  });
});

describe("question history", () => {
  const entries = ["first", "second", "third"];
  const walk = (dirs: ("backward" | "forward")[], start = "") => {
    let position: HistoryPosition | null = null;
    let current = start;
    const seen: (string | null)[] = [];
    for (const direction of dirs) {
      const next = step({ direction, entries, position, current });
      seen.push(next ? next.prompt : null);
      if (next) {
        position = next.position;
        current = next.prompt;
      }
    }
    return seen;
  };

  it("walks back from an empty box and forward again, past the newest to an empty box", () => {
    expect(walk(["backward", "backward", "backward", "backward", "forward", "forward", "forward"])).toEqual([
      "third",
      "second",
      "first",
      null,
      "second",
      "third",
      "",
    ]);
  });

  it("never overwrites a draft", () => {
    expect(walk(["backward"], "my draft")).toEqual([null]);
    expect(walk(["forward"])).toEqual([null]);
  });

  it("stops recalling once the recalled question was edited", () => {
    const first = step({ direction: "backward", entries, position: null, current: "" });
    expect(step({ direction: "backward", entries, position: first!.position, current: "third, edited" })).toBeNull();
  });

  it("keeps one copy of a repeated question and a bounded list", () => {
    expect(remember(["a", "b"], "  b ")).toEqual(["a", "b"]);
    expect(remember(["a"], "   ")).toEqual(["a"]);
    expect(remember(["a", "b", "c"], "d", 3)).toEqual(["b", "c", "d"]);
  });

  it("recalls only from the first line going up and the last line going down", () => {
    expect(caretOnEdge("one\ntwo", 2, 2, "backward")).toBe(true);
    expect(caretOnEdge("one\ntwo", 5, 5, "backward")).toBe(false);
    expect(caretOnEdge("one\ntwo", 5, 5, "forward")).toBe(true);
    expect(caretOnEdge("one\ntwo", 0, 3, "backward")).toBe(false);
  });
});

describe("runtime", () => {
  it("formats like T3 Code: seconds, then minutes and seconds, then hours and minutes", () => {
    expect([0, 9.7, 65, 3725].map(formatElapsed)).toEqual(["0s", "9s", "1m 05s", "1h 02m"]);
  });

  it("times a run from when it was first seen live until it was seen finished", () => {
    const clock = new RunClock();
    clock.observe("r", false, 0);
    expect(clock.elapsed("r", 10)).toBeNull();
    clock.observe("r", true, 1000);
    clock.observe("r", true, 5000);
    expect(clock.elapsed("r", 7000)).toBe(6000);
    clock.observe("r", false, 9000);
    expect(clock.elapsed("r", 60_000)).toBe(8000);
    expect(clock.running("r")).toBe(false);
  });
});
