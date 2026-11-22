import { firstSentence, groupRuns, GROUP_TITLE, liveLine, type RunGroup } from "../../agent-ui/activity";
import { roleOf, type ActivityRecord, type AgentRole, type ProposalView, type ReceiptLink, type RunSummary } from "../../lib/agent";

export type ThreadState = "working" | "awaiting approval" | "paused" | "settled" | "unknown";

export interface LiveFixThread {
  id: string;
  incidentId: string | null;
  title: string;
  state: ThreadState;
  at: string | null;
  group: RunGroup | null;
  run: RunSummary | null;
  proposals: ProposalView[];
}

const latest = <T>(entries: readonly T[]): T | undefined => entries[entries.length - 1];

/** The index includes server summaries even when their activity is outside the retained window. */
export function liveFixThreads(records: ActivityRecord[], runs: RunSummary[], proposals: ProposalView[], replayState: string | null): LiveFixThread[] {
  const groups = new Map(groupRuns(records, runs).filter((g) => g.runId !== null).map((g) => [g.key, g]));
  const summaries = new Map(runs.map((run) => [run.run_id, run]));
  const byRun = new Map<string, ProposalView[]>();
  for (const proposal of proposals) byRun.set(proposal.run_id, [...(byRun.get(proposal.run_id) ?? []), proposal]);
  const ids = new Set([...groups.keys(), ...summaries.keys(), ...byRun.keys()]);
  return [...ids].map((id): LiveFixThread => {
    const group = groups.get(id) ?? null;
    const run = summaries.get(id) ?? null;
    const work = group?.records ?? [];
    const actions = byRun.get(id) ?? [];
    const last = latest(work);
    const question = work.find((record) => record.kind === "chat_question")?.text;
    const incidentId = run?.incident_id ?? latest(work.filter((record) => record.incident_id))?.incident_id ?? latest(actions)?.incident_ref ?? null;
    const awaiting = actions.some((action) => action.state === "AWAIT_OPERATOR");
    const recordedProgress = replayState !== null && !run && last && last.seq === latest(records)?.seq;
    let state: ThreadState = "unknown";
    if (awaiting) state = "awaiting approval";
    else if (group?.finished || (run && run.status !== "running")) state = "settled";
    else if (run?.status === "running" || recordedProgress) {
      if (replayState === "completed") state = "settled";
      else if (replayState === "paused" || replayState === "awaiting_approval") state = "paused";
      else if (replayState === null || replayState === "playing") state = "working";
    }
    const kind = run?.kind ?? group?.kind ?? "investigate";
    return {
      id, incidentId, state, group, run, proposals: actions,
      title: (question && firstSentence(question)) || (incidentId ? `${GROUP_TITLE[kind]} · ${incidentId}` : GROUP_TITLE[kind]),
      at: last?.sim_ts ?? run?.sim_ts ?? latest(actions)?.effective_at ?? null,
    };
  }).sort((a, b) => (b.at ?? "").localeCompare(a.at ?? "") || (b.group?.lastSeq ?? 0) - (a.group?.lastSeq ?? 0) || a.id.localeCompare(b.id));
}

export function threadForIncident(threads: LiveFixThread[], incidentId: string): LiveFixThread | undefined {
  const matching = threads.filter((thread) => thread.incidentId === incidentId);
  return matching.find((thread) => thread.state === "awaiting approval")
    ?? matching.find((thread) => (thread.run?.kind ?? thread.group?.kind) === "investigate")
    ?? matching[0];
}

export function matchesThread(thread: LiveFixThread, query: string): boolean {
  const index = [thread.title, thread.id, thread.incidentId, thread.state, thread.group?.kind, ...(thread.group?.roles ?? [])].join(" ").toLowerCase();
  return query.toLowerCase().trim().split(/\s+/).every((term) => index.includes(term));
}

function timestamp(value: string): number {
  return Date.parse(value.endsWith("Z") || /[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`);
}

/** Simulated timestamps can share a tick. A shared tick cannot establish a wall-clock runtime. */
export function recordedSpan(first: string | undefined, last: string | undefined): number | null {
  if (!first || !last) return null;
  const seconds = (timestamp(last) - timestamp(first)) / 1000;
  return Number.isFinite(seconds) && seconds > 0 ? seconds : null;
}

export function lineageOf(thread: LiveFixThread) {
  const records = thread.group?.records ?? [];
  const roles = new Map<AgentRole, ActivityRecord[]>();
  for (const record of records) {
    const role = roleOf(record);
    roles.set(role, [...(roles.get(role) ?? []), record]);
  }
  const active = thread.state === "working" && thread.group ? liveLine(thread.group).role : null;
  return [...roles].map(([role, work]) => {
    const last = latest(work)!;
    const checks = thread.group?.checks.filter((check) => check.role === role) ?? [];
    return { role, last, seconds: recordedSpan(work[0]?.sim_ts, last.sim_ts), working: role === active, checks };
  });
}

export function uniqueReceipts(links: ReceiptLink[]): ReceiptLink[] {
  return [...new Map(links.map((link) => [JSON.stringify([link.run_id, link.world_revision, link.receipt_id]), link])).values()];
}
