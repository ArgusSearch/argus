import { describe, expect, it } from "vitest";
import type { ActivityRecord, ProposalView } from "../../lib/agent";
import { activityAvatarRole, avatarCues, proposalAvatarCue, WORK_CUE_MS } from "../avatars/state";
import tape from "../tapes/s4-agent.json";

const real = tape.activity as unknown as ActivityRecord[];
const proposal = tape.actions[0] as unknown as ProposalView;
const now = 10000;

function step(seq: number, kind: ActivityRecord["kind"], fields: Partial<ActivityRecord> = {}): ActivityRecord {
  return { ...real[0], seq, kind, role: undefined, run_id: "case", text: "Step from the activity stream", action_id: null, tool: null, ...fields };
}

function recent(...records: ActivityRecord[]): Map<number, number> {
  return new Map(records.map((record) => [record.seq, now + WORK_CUE_MS]));
}

describe("live avatar states", () => {
  it("hydrates historical activity quietly and follows the next Watcher tick", () => {
    expect(avatarCues(real, [], [], new Map(), now).roles).toEqual({});
    const watched = step(99, "watch", { run_id: null, text: "Scored the shop's metrics" });
    const records = [...real, watched];
    const until = recent(watched);
    expect(avatarCues(records, [], [], until, now)).toEqual({
      roles: { watcher: { status: "working", key: 99, text: watched.text, runId: null, actionId: null } },
      nextExpiry: now + WORK_CUE_MS,
    });
    expect(avatarCues(records, [], [], until, now + WORK_CUE_MS).roles).toEqual({});
  });

  it("shows an open step from a running case and clears it when that case closes", () => {
    const check = step(1, "tool_call", { tool: "segment_search", text: "Check PayCo on Android in Germany" });
    const watch = step(2, "watch", { run_id: null });
    const finished = step(3, "run_finished");
    const runs = [{ run_id: "case", status: "running" as const }];
    expect(avatarCues([check, watch], [], runs, new Map(), now).roles.detective).toMatchObject({
      status: "working", text: check.text, key: check.seq,
    });
    expect(avatarCues([check, watch, finished], [], runs, recent(check, watch), now).roles.detective).toBeUndefined();
  });

  it("uses the server role and handles legacy Skeptic and Ask records", () => {
    const named = step(1, "tool_call", { role: "cartographer", tool: "check_identities" });
    const skeptic = step(2, "tool_result", { tool: "holdout_check" });
    const asked = step(3, "chat_question", { actor: "operator", role: "operator", run_id: "ask" });
    expect([named, skeptic, asked].map(activityAvatarRole)).toEqual(["cartographer", "skeptic", "narrator"]);
    expect(avatarCues([named, skeptic, asked], [], [], recent(named, skeptic, asked), now).roles).toMatchObject({
      skeptic: { status: "working", key: 2 },
      narrator: { status: "working", key: 3 },
    });
  });

  it("pulses a confirmed approval, clears it on a recorded decision, and binds work to the same proposal", () => {
    const decided = step(1, "action_decided", { action_id: proposal.id });
    const applied = step(2, "action_applied", { action_id: proposal.id });
    expect(avatarCues([], [proposal], [], new Map(), now).roles.operator).toMatchObject({ status: "waiting", key: proposal.id });
    expect(avatarCues([decided], [proposal], [], recent(decided), now).roles.operator).toBeUndefined();
    const work = avatarCues([decided, applied], [proposal], [], recent(applied), now).roles.operator;
    const applying = { ...proposal, state: "APPLYING" as const };
    expect(proposalAvatarCue(applying, work)).toMatchObject({ status: "working", key: applied.seq });
    expect(proposalAvatarCue({ ...applying, id: "other" }, work).status).toBe("idle");
    expect(proposalAvatarCue({ ...proposal, state: "EXPIRED" }, work).status).toBe("done");
  });
});
