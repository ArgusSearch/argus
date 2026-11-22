// The agent's activity as runs, the way a coding agent's work log reads (pattern from T3 Code's work-log
// presentation, pingdotgg/t3code, MIT; rewritten for Argus): the records of one run form one group, a check and its
// result are one row, a finished run folds to one summary line ("Ran 3 checks: 2 confirmed, 1 ruled out") and the
// running one says what it is doing now. Pure functions; the page renders what these return.

import { roleOf, roleOfTool, type ActivityRecord, type AgentRole, type ProposalView, type RunSummary } from "../lib/agent";

/** A check the agent ran: the call with its hypothesis, and the result once it came back. */
export interface CheckStep {
  kind: "check";
  key: string;
  tool: string;
  role: AgentRole;
  call: ActivityRecord | null;
  result: ActivityRecord | null;
}

/** Any other step, one record. */
export interface RecordStep {
  kind: "record";
  key: string;
  record: ActivityRecord;
}

export type Step = CheckStep | RecordStep;

export type GroupKind = "investigate" | "ask" | "morning" | "verify_effect" | "quiet";

export interface RunGroup {
  /** the run id, or `quiet:<first seq>` for a stretch of records outside any run (quiet hours) */
  key: string;
  runId: string | null;
  kind: GroupKind;
  run: RunSummary | null;
  records: ActivityRecord[];
  steps: Step[];
  checks: CheckStep[];
  /** ids of the actions this run proposed, in order */
  proposed: string[];
  /** the run wrote its run_finished record */
  finished: boolean;
  /** the roles that took part, in the order they first appeared */
  roles: AgentRole[];
  firstSeq: number;
  lastSeq: number;
}

const RUN_KINDS = new Set<GroupKind>(["investigate", "ask", "morning", "verify_effect"]);

function inferKind(records: ActivityRecord[], run: RunSummary | null): GroupKind {
  if (run && RUN_KINDS.has(run.kind)) return run.kind;
  if (records.some((r) => r.kind === "chat_question" || r.kind === "chat_answer")) return "ask";
  if (records.some((r) => r.kind === "effect_checked")) return "verify_effect";
  return "investigate";
}

/** The steps of one run: each tool_call paired with the first later tool_result of the same check. */
export function stepsOf(records: ActivityRecord[]): Step[] {
  const steps: Step[] = [];
  // open calls per tool, oldest first: a result answers the oldest call of its tool that has none yet
  const open = new Map<string, CheckStep[]>();
  for (const r of records) {
    if (r.kind === "tool_call" || r.kind === "tool_result") {
      const tool = r.tool ?? r.observation?.tool ?? "check";
      if (r.kind === "tool_call") {
        const step: CheckStep = { kind: "check", key: `c${r.seq}`, tool, role: roleOf(r), call: r, result: null };
        steps.push(step);
        open.set(tool, [...(open.get(tool) ?? []), step]);
      } else {
        const waiting = open.get(tool);
        const step = waiting?.shift();
        if (step) step.result = r;
        else steps.push({ kind: "check", key: `c${r.seq}`, tool, role: roleOf(r), call: null, result: r });
      }
      continue;
    }
    steps.push({ kind: "record", key: `r${r.seq}`, record: r });
  }
  return steps;
}

/** Records as runs, in the order each run first appeared; consecutive records outside a run form one quiet group. */
export function groupRuns(records: ActivityRecord[], runs: RunSummary[] = []): RunGroup[] {
  const byRun = new Map(runs.map((r) => [r.run_id, r]));
  const buckets = new Map<string, ActivityRecord[]>();
  let quiet: string | null = null;
  for (const r of records) {
    let key: string;
    if (r.run_id) {
      key = r.run_id;
      quiet = null;
    } else {
      quiet ??= `quiet:${r.seq}`;
      key = quiet;
    }
    const bucket = buckets.get(key);
    if (bucket) bucket.push(r);
    else buckets.set(key, [r]);
  }
  const groups: RunGroup[] = [];
  for (const [key, recs] of buckets) {
    const runId = key.startsWith("quiet:") ? null : key;
    const run = runId ? (byRun.get(runId) ?? null) : null;
    const steps = stepsOf(recs);
    const roles: AgentRole[] = [];
    for (const r of recs) {
      const role = roleOf(r);
      if (!roles.includes(role)) roles.push(role);
    }
    groups.push({
      key,
      runId,
      kind: runId ? inferKind(recs, run) : "quiet",
      run,
      records: recs,
      steps,
      checks: steps.filter((s): s is CheckStep => s.kind === "check"),
      proposed: recs.filter((r) => r.kind === "action_proposed" && r.action_id).map((r) => r.action_id as string),
      finished: recs.some((r) => r.kind === "run_finished"),
      roles,
      firstSeq: recs[0].seq,
      lastSeq: recs[recs.length - 1].seq,
    });
  }
  return groups;
}

/**
 * Whether a run is still going. A run that wrote run_finished is over; otherwise the run summary says so, and while
 * a recorded presentation streams its records the run is live until its finish arrives.
 */
export function isLive(group: RunGroup, streaming = false): boolean {
  if (group.kind === "quiet" || group.finished) return false;
  if (group.run?.status === "running") return true;
  return streaming || group.run === null;
}

/* ------------------------------------------------------------------ words */

export const GROUP_TITLE: Record<GroupKind, string> = {
  investigate: "Investigation",
  ask: "Question",
  morning: "Morning report",
  verify_effect: "Effect check",
  quiet: "Quiet hours",
};

/** Outcomes that back the suspicion, and those that rule it out (the rest are neutral findings). */
const SUPPORTS = /confirm|consistent|valid|held|support|unusual|found/i;
const RULES_OUT = /refut|ruled|reject|inconsistent|not[_ ]found|no[_ ]effect/i;

export type OutcomeTone = "ok" | "alarm" | "muted";

export function outcomeTone(outcome: string | null | undefined): OutcomeTone {
  if (!outcome) return "muted";
  if (RULES_OUT.test(outcome)) return "alarm";
  return SUPPORTS.test(outcome) ? "ok" : "muted";
}

const words = (s: string) => s.replace(/_/g, " ").toLowerCase();

/** How many checks came back with each outcome, in the order the outcomes first appeared. */
export function outcomeCounts(checks: CheckStep[]): { outcome: string; count: number; tone: OutcomeTone }[] {
  const counts = new Map<string, number>();
  for (const c of checks) {
    const o = c.result?.observation?.outcome;
    if (!o) continue;
    counts.set(o, (counts.get(o) ?? 0) + 1);
  }
  return [...counts].map(([outcome, count]) => ({ outcome, count, tone: outcomeTone(outcome) }));
}

const plural = (n: number, one: string, many = `${one}s`) => `${n} ${n === 1 ? one : many}`;

/** The one line a folded run reads as: "Ran 3 checks: 1 found, 1 consistent, 1 unusual". */
export function groupSummary(group: RunGroup, live = false): string {
  if (group.kind === "quiet") return `Watched ${plural(group.records.length, "quiet hour")}, no model call`;
  const n = group.checks.length;
  const pending = group.checks.filter((c) => !c.result).length;
  if (n === 0) {
    if (group.kind === "ask") return live ? "Reading the question" : "Answered from what it already knew";
    return live ? "Getting started" : "No checks";
  }
  const head = live ? `${pending ? "Running" : "Ran"} ${plural(n, "check")}` : `Ran ${plural(n, "check")}`;
  const counts = outcomeCounts(group.checks);
  return counts.length ? `${head}: ${counts.map((c) => `${c.count} ${words(c.outcome)}`).join(", ")}` : head;
}

/** What the verdict gate admitted, if the run reached it. */
export function gateOf(group: RunGroup): { claimed: string; admitted: string } | null {
  if (group.run?.gate) return { claimed: group.run.gate.claimed, admitted: group.run.gate.admitted };
  for (let i = group.records.length - 1; i >= 0; i--) {
    const m = /verdict (\w+) \(model claimed (\w+)\)/.exec(group.records[i].kind === "gate" ? group.records[i].text : "");
    if (m) return { admitted: m[1], claimed: m[2] };
  }
  return null;
}

/** The model spend of a run: its summary when the API sent one, else the sum of its model calls. */
export function usdOf(group: RunGroup): number {
  if (group.run) return group.run.usd;
  return group.records.reduce((s, r) => s + (r.usd ?? 0), 0);
}

/**
 * The first sentence of a thought, as plain text (T3 Code's live thought line, rewritten): a leading bold heading
 * wins, markdown marks are dropped, whitespace folds.
 */
export function firstSentence(markdown: string): string {
  const heading = /^\s*\*\*([^*\r\n]+)\*\*[ \t]*\r?(?:\n|$)/.exec(markdown)?.[1];
  const text = (heading ?? markdown)
    .replace(/!?\[([^\]]*)\]\([^)]*\)/g, "$1")
    .replace(/^[ \t]*(?:#{1,6}|[-*+]|\d+\.)[ \t]+/gm, "")
    .replace(/`+|\*\*|~~/g, "")
    .replace(/\s+/g, " ")
    .trim();
  if (heading !== undefined) return text;
  const end = /[.?!]["')]?(?=\s)/.exec(text);
  return end ? text.slice(0, end.index + end[0].length) : text;
}

/** What a live run is doing right now, in one line, and who is doing it. */
export function liveLine(group: RunGroup): { role: AgentRole; verb: string; text: string } {
  const running = [...group.checks].reverse().find((c) => c.call && !c.result);
  const last = group.records[group.records.length - 1];
  if (running && running.call && running.call.seq === lastCheckCallSeq(group)) {
    const hyp = running.call.observation?.hypothesis ?? running.call.text;
    return { role: running.role, verb: `Runs ${running.tool}`, text: hyp ? firstSentence(hyp) : "" };
  }
  if (last.kind === "thought") return { role: roleOf(last), verb: "Thinks", text: firstSentence(last.text) };
  if (last.kind === "tool_result") {
    const tool = last.tool ?? last.observation?.tool ?? null;
    return { role: roleOfTool(tool), verb: "Reads the result", text: last.observation?.summary ? firstSentence(last.observation.summary) : "" };
  }
  if (last.kind === "gate") return { role: "skeptic", verb: "Verdict gate", text: firstSentence(last.text) };
  if (last.kind === "chat_question") return { role: "narrator", verb: "Reads the question", text: firstSentence(last.text) };
  return { role: roleOf(last), verb: "Working", text: firstSentence(last.text) };
}

function lastCheckCallSeq(group: RunGroup): number {
  // the call is current only while nothing but its own thinking came after it
  for (let i = group.records.length - 1; i >= 0; i--) {
    const r = group.records[i];
    if (r.kind === "tool_call") return r.seq;
    if (r.kind !== "thought") return -1;
  }
  return -1;
}

/* ------------------------------------------------------------------ approvals */

/** Proposals still waiting for a person. */
export function pendingProposals(proposals: ProposalView[]): ProposalView[] {
  return proposals.filter((p) => p.state === "AWAIT_OPERATOR");
}

/** The proposals a run made: by the ids its records name, else by the proposal's own run id. */
export function proposalsOf(group: RunGroup, proposals: ProposalView[]): ProposalView[] {
  const ids = new Set(group.proposed);
  return proposals.filter((p) => ids.has(p.id) || (group.runId !== null && p.run_id === group.runId && !ids.size));
}

/** The page title with the count of waiting decisions in front, like an unread count: "(1) Argus". */
export function titleWithCount(base: string, waiting: number): string {
  const clean = base.replace(/^\(\d+\) /, "");
  return waiting > 0 ? `(${waiting}) ${clean}` : clean;
}

/* ------------------------------------------------------------------ evidence for an answer */

const linkKey = (l: { run_id: string; receipt_id: string }) => `${l.run_id}/${l.receipt_id}`;

/**
 * The checks behind an Ask answer: every check of the answer's own run, and every check elsewhere whose receipts
 * the answer cites. Ordered as they ran, each once.
 */
export function evidenceChecks(
  answer: { run_id?: string | null; receipt_links: { run_id: string; receipt_id: string }[]; claims: { receipts: { run_id: string; receipt_id: string }[] }[] },
  records: ActivityRecord[],
): CheckStep[] {
  const cited = new Set([...answer.receipt_links, ...answer.claims.flatMap((c) => c.receipts)].map(linkKey));
  // paired within each run, so a check of one run never takes the result of another
  const checks = groupRuns(records).flatMap((g) => g.checks.filter((c) => c.result !== null));
  return checks.filter((c) => {
    const r = c.result as ActivityRecord;
    if (answer.run_id && r.run_id === answer.run_id) return true;
    const links = [...r.receipt_links, ...(r.observation?.receipt_refs ?? [])];
    return links.some((l) => cited.has(linkKey(l)));
  });
}
