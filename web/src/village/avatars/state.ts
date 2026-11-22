import { roleOf, type ActivityKind, type ActivityKindV2, type ActivityRecord, type ProposalView, type RunSummary } from "../../lib/agent";
import type { RoleId } from "../roles";

export type AvatarStatus = "idle" | "working" | "waiting" | "done" | "sleeping";

export interface AvatarCue {
  status: AvatarStatus;
  key?: number | string;
  text?: string;
  runId?: string | null;
  actionId?: string | null;
}

export type AvatarCues = Partial<Record<RoleId, AvatarCue>>;
export const IDLE_AVATAR: AvatarCue = { status: "idle" };
export const WORK_CUE_MS = 3200;

const STARTS = new Set<ActivityKind | ActivityKindV2>(["run_started", "thought", "tool_call", "hypothesis", "chat_question"]);
const STEPS = new Set<ActivityKind | ActivityKindV2>([
  "watch", "tool_result", "gate", "critic", "report", "memory", "action_applied", "effect_checked", "chat_answer",
]);

/** The API's role wins, except that a person's question starts the Narrator's work. */
export function activityAvatarRole(record: ActivityRecord): RoleId {
  const kind = record.kind as ActivityKind | ActivityKindV2;
  if (kind === "chat_question") return "narrator";
  if (!record.role && kind === "critic") return "skeptic";
  return roleOf(record);
}

export function activityAvatarCue(record: ActivityRecord): AvatarCue | undefined {
  if (!STARTS.has(record.kind) && !STEPS.has(record.kind)) return;
  return {
    status: "working",
    key: record.seq,
    text: record.text.trim() || record.observation?.summary || record.tool?.replace(/_/g, " "),
    runId: record.run_id,
    actionId: record.action_id,
  };
}

export function proposalAvatarCue(proposal: ProposalView, operator?: AvatarCue): AvatarCue {
  if (proposal.state === "AWAIT_OPERATOR") {
    return { status: "waiting", key: proposal.id, text: proposal.action, runId: proposal.run_id, actionId: proposal.id };
  }
  if (proposal.state === "APPLYING" || proposal.state === "APPLIED" || proposal.state === "VERIFYING") {
    return operator?.actionId === proposal.id && operator.status === "working" ? operator : IDLE_AVATAR;
  }
  return { status: "done" };
}

/** Live records carry simulated timestamps. Only newly received records get a wall-clock motion window. */
export function avatarCues(
  records: readonly ActivityRecord[],
  proposals: readonly ProposalView[],
  runs: readonly Pick<RunSummary, "run_id" | "status">[],
  until: ReadonlyMap<number, number>,
  now: number,
): { roles: AvatarCues; nextExpiry: number } {
  const running = new Set(runs.filter((run) => run.status === "running").map((run) => run.run_id));
  const latestRun = new Map<string, ActivityRecord>();
  const decided = new Set<string>();
  for (const record of records) {
    if (record.run_id) latestRun.set(record.run_id, record);
    if (record.action_id && (record.kind === "action_decided" || record.kind === "action_applied" || record.kind === "effect_checked")) {
      decided.add(record.action_id);
    }
  }

  const roles: AvatarCues = {};
  let nextExpiry = Infinity;
  for (let i = records.length - 1; i >= 0; i--) {
    const record = records[i];
    const role = activityAvatarRole(record);
    if (roles[role]) continue;
    const cue = activityAvatarCue(record);
    if (!cue) continue;
    const starts = STARTS.has(record.kind);
    if (starts && record.run_id && latestRun.get(record.run_id) !== record) continue;
    const active = starts && record.run_id && running.has(record.run_id);
    const expires = until.get(record.seq) ?? 0;
    if (expires <= now && !active) continue;
    roles[role] = cue;
    if (!active) nextExpiry = Math.min(nextExpiry, expires);
  }

  const waiting = proposals.findLast((proposal) => proposal.state === "AWAIT_OPERATOR" && !decided.has(proposal.id));
  if (waiting) roles.operator = proposalAvatarCue(waiting);
  return { roles, nextExpiry };
}
