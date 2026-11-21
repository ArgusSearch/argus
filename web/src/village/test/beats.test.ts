import { describe, expect, it } from "vitest";
import { buildBeats, roleOfTool } from "../beats";
import { ROLES } from "../roles";
import { idleBubbles, timeline, villageAt } from "../timeline";
import type { ActivityRecord, VillageTape } from "../types";
import s1Tape from "../tapes/s1.json";
import s4Tape from "../tapes/s4.json";

const s1 = s1Tape as unknown as VillageTape;
const s4 = s4Tape as unknown as VillageTape;
const idle = idleBubbles(ROLES);

// the recordings the tapes were built from (tools/build-tapes.mjs): a tape must not drift from its fixture
const fixtures = import.meta.glob<string>(["../../../../fixtures/events.jsonl", "../../../../fixtures/s4/events.jsonl"], {
  query: "?raw",
  import: "default",
  eager: true,
});

const order = (beats: { role: string; caseId: string | null }[]) =>
  beats.filter((b) => b.caseId).reduce<string[]>((acc, b) => (acc[acc.length - 1] === b.role ? acc : [...acc, b.role]), []);

describe("tapes", () => {
  it("carry every investigation step and incident change of their recording", () => {
    for (const [path, tape] of [
      ["../../../../fixtures/events.jsonl", s1],
      ["../../../../fixtures/s4/events.jsonl", s4],
    ] as const) {
      const raw = fixtures[path];
      expect(raw, path).toBeTruthy();
      const events = raw
        .split("\n")
        .filter(Boolean)
        .map((l) => JSON.parse(l) as { seq: number; type: string });
      const keyed = (list: { seq: number; type: string }[]) =>
        list.filter((e) => ["investigation_step", "incident_updated", "anomaly_opened", "edge_status", "tick"].includes(e.type)).map((e) => `${e.seq}:${e.type}`);
      expect(keyed(tape.events)).toEqual(keyed(events));
    }
  });
});

describe("buildBeats on the S1 recording", () => {
  const open = buildBeats(s1, { decision: null });

  it("walks the case Watcher -> Detective -> Skeptic -> Narrator -> Operator and stops at the approval", () => {
    const walk = order(open);
    expect(walk[0]).toBe("watcher");
    const firstOf = (role: string) => walk.indexOf(role);
    expect(firstOf("detective")).toBeGreaterThan(0);
    expect(firstOf("skeptic")).toBeGreaterThan(firstOf("detective"));
    expect(walk.lastIndexOf("narrator")).toBeGreaterThan(walk.lastIndexOf("skeptic"));
    expect(walk[walk.length - 1]).toBe("operator");
    const last = open[open.length - 1];
    expect(last.gate?.action).toMatch(/Route DE-android payments/);
    expect(last.role).toBe("operator");
  });

  it("names the suspect the Skeptic checks and rules out the false trails", () => {
    const holdouts = open.filter((b) => b.log[0]?.tool === "holdout_check");
    expect(holdouts).toHaveLength(3);
    expect(holdouts[0].doing).toMatch(/^Checking PayCo/);
    expect(holdouts[0].doing).toMatch(/outside DE · android · PayCo/);
    expect(holdouts.filter((b) => b.outcome === "refuted").map((b) => b.done)).toEqual([
      expect.stringMatching(/^Ruled out: android-app 8\.3\.0/),
      expect.stringMatching(/^Ruled out: checkout-service 1\.2\.6/),
    ]);
  });

  it("folds the quiet hours and the edge tests", () => {
    const edges = open.filter((b) => b.kind === "edges");
    expect(edges).toHaveLength(1);
    expect(edges[0].log).toHaveLength(34);
    const watch = open.filter((b) => b.kind === "watch");
    expect(watch[0].done).toMatch(/quiet hours watched/);
    expect(watch.length).toBe(4);
  });

  it("an approval on a tape without a recorded action says that nothing runs, then the recording plays on", () => {
    const approved = buildBeats(s1, { decision: "approve" });
    const decision = approved.find((b) => b.kind === "decision");
    expect(decision?.done).toMatch(/nothing runs/);
    const after = approved.slice(approved.indexOf(decision!) + 1);
    expect(after.filter((b) => b.kind === "lifecycle").map((b) => b.role)).toEqual(["watcher", "watcher"]);
    expect(after[after.length - 1].kind).toBe("watch");
    expect(approved.slice(0, open.length).map((b) => b.key)).toEqual(open.map((b) => b.key));
  });

  it("a denial is recorded as such", () => {
    const denied = buildBeats(s1, { decision: "deny" });
    expect(denied.find((b) => b.kind === "decision")?.outcome).toBe("denied");
  });
});

describe("S4", () => {
  it("asks to roll back the pacer and ends watching after the decision", () => {
    const open = buildBeats(s4, { decision: null });
    expect(open[open.length - 1].gate?.action).toMatch(/Roll back dep_ad-pacer_1\.7\.0/);
    const done = buildBeats(s4, { decision: "approve" });
    expect(done[done.length - 1].role).toBe("watcher");
    expect(order(open)).toContain("cartographer");
  });
});

describe("villageAt", () => {
  const tl = timeline(buildBeats(s1, { decision: null }));

  it("is idle before the first beat and waits at the gate at the end", () => {
    const start = villageAt(tl, -1, idle);
    expect(start.roles.detective.status).toBe("idle");
    expect(start.roles.detective.bubble).toBe(idle.detective);
    const end = villageAt(tl, tl.total, idle);
    expect(tl.waiting).toBe(true);
    expect(end.gate?.action).toMatch(/Route/);
    expect(end.roles.operator.status).toBe("waiting");
    expect(end.finished).toBe(false);
    expect(end.roles.skeptic.log.length).toBe(4);
  });

  it("flies the case orb between igloos at a hand-over", () => {
    const i = tl.slots.findIndex((s) => s.from === "detective" && s.beat.role === "skeptic");
    expect(i).toBeGreaterThan(0);
    const mid = villageAt(tl, tl.slots[i].start + 0.3, idle);
    const orb = mid.orbs.find((o) => o.caseId === "an_0001");
    expect(orb).toMatchObject({ from: "detective", at: "skeptic" });
    expect(orb!.progress).toBeGreaterThan(0);
    expect(orb!.progress).toBeLessThan(1);
    expect(mid.roles.skeptic.bubble).toMatch(/^Receiving/);
    const later = villageAt(tl, tl.slots[i].start + tl.slots[i].length - 0.01, idle);
    expect(later.orbs[0]).toMatchObject({ from: null, at: "skeptic", progress: 1 });
  });

  it("keeps a role's last result once it moved on", () => {
    const i = tl.slots.findIndex((s) => s.beat.kind === "verdict");
    const s = villageAt(tl, tl.slots[i].start + 0.1, idle);
    expect(s.roles.skeptic.status).toBe("done");
    expect(s.roles.skeptic.bubble).toMatch(/No earlier week/);
  });
});

describe("agent activity", () => {
  const rec = (seq: number, kind: ActivityRecord["kind"], extra: Partial<ActivityRecord> = {}): ActivityRecord => ({
    seq,
    run_id: "run_1",
    sim_ts: "2026-11-20T02:00:00",
    kind,
    stage: "ACT",
    actor: "host",
    text: `${kind} ${seq}`,
    anomaly_id: "an_0001",
    ...extra,
  });
  const tape: VillageTape = {
    ...s4,
    activity: [
      rec(1, "run_started"),
      rec(2, "tool_call", { tool: "holdout_check" }),
      rec(3, "tool_result", { tool: "check_control_group" }),
      rec(4, "action_proposed", { action_id: "act_0001", incident_id: "INC-0001" }),
      rec(5, "action_applied", { action_id: "act_0001", gate_action: "act_0001" }),
    ],
    actions: [],
    continuations: { approve: { events: [], activity: [rec(6, "effect_checked", { text: "VERIFIED against the untouched twin" })], actions: [] } },
  };

  it("maps tools to their roles and the proposal to the Operator's gate", () => {
    expect(roleOfTool("holdout_check")).toBe("skeptic");
    expect(roleOfTool("check_control_group")).toBe("market");
    const open = buildBeats(tape, { decision: null });
    expect(open.map((b) => b.role).slice(-4)).toEqual(["detective", "skeptic", "market", "operator"]);
    expect(open[open.length - 1].gate?.actionId).toBe("act_0001");
    // the agent's run replaces the Stage-2 trail of the same anomaly
    expect(open.some((b) => b.log[0]?.tool === "segment_search")).toBe(false);
  });

  it("releases the gated records and the approve continuation only after an approval", () => {
    const approved = buildBeats(tape, { decision: "approve" });
    const kinds = approved.filter((b) => b.role === "operator").map((b) => b.kind);
    expect(kinds).toEqual(["proposal", "decision", "apply", "effect"]);
    expect(approved.find((b) => b.kind === "decision")?.done).toMatch(/applying in the simulator/);
    const denied = buildBeats(tape, { decision: "deny" });
    expect(denied.some((b) => b.kind === "apply" || b.kind === "effect")).toBe(false);
  });
});
