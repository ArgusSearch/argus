import { roleOfTool, type AgentRole, type ProposalView } from "../lib/agent";
import type { RunView, StepView } from "../lib/store";
import type { Graph, Incident, Note } from "../lib/types";

/* ------------------------------------------------------------------ autonomy */

interface Rule {
  id: string;
  when: string;
  behavior: string;
}

export interface Autonomy {
  decides_alone: Rule[];
  asks_first: Rule[];
  probation: { kind: "node" | "edge"; id: string; status: string }[];
  playbooks: { id: string; name: string; steps: { id: string; label: string; question: string }[] }[];
}

export type Level = "alone" | "asks" | "off";

/**
 * Which agent owns which rule of GET /autonomy. The rule ids are the API's; the owner follows the job each agent
 * does in the village (web/src/village/roles.ts). The Market Analyst has no rule of its own: it runs inside the
 * Detective's investigation.
 */
const RULE_OWNER: Record<string, AgentRole> = {
  monitor: "watcher",
  defer_late_data: "watcher",
  investigate: "detective",
  hold_alert: "skeptic",
  review_ambiguous_cause: "skeptic",
  retest_graph: "cartographer",
  review_probation: "cartographer",
  manage_incident: "narrator",
  approve_action: "operator",
};

/** Short names for the rules, in the words the pages use. Unknown rules show their id. */
const RULE_NAME: Record<string, string> = {
  monitor: "Score every metric each hour",
  defer_late_data: "Wait for late data",
  investigate: "Investigate a crossing",
  hold_alert: "Hold back planned changes",
  review_ambiguous_cause: "Unsure cause",
  retest_graph: "Re-test formula edges",
  review_probation: "Promote a probation edge",
  manage_incident: "File and close incidents",
  approve_action: "Apply a fix",
};

interface RuleRow extends Rule {
  level: Level;
  name: string;
}

interface AgentRules {
  role: AgentRole;
  rules: RuleRow[];
}

/** The rules of GET /autonomy per agent, in AGENT order; a rule with no known owner lands under `other`. */
export function rulesByAgent(autonomy: Autonomy, order: readonly AgentRole[]): { agents: AgentRules[]; other: RuleRow[] } {
  const rows: RuleRow[] = [
    ...autonomy.decides_alone.map((r) => ({ ...r, level: "alone" as const, name: RULE_NAME[r.id] ?? r.id })),
    ...autonomy.asks_first.map((r) => ({ ...r, level: "asks" as const, name: RULE_NAME[r.id] ?? r.id })),
  ];
  const agents = order.map((role) => ({ role, rules: rows.filter((r) => RULE_OWNER[r.id] === role) }));
  return { agents, other: rows.filter((r) => !RULE_OWNER[r.id]) };
}

/* ------------------------------------------------------------------ steps */

interface SeenChange {
  ref: string;
  log: string;
  ts: string;
  description: string;
  scope: Record<string, string[]>;
  uplift: number | null;
  delivered: number | null;
  status: string | null;
  receipts: string[];
}

interface RawEvent {
  log?: unknown;
  ref?: unknown;
  ts?: unknown;
  description?: unknown;
  scope?: unknown;
}

function asEvent(raw: unknown): Omit<SeenChange, "uplift" | "delivered" | "status" | "receipts"> | null {
  if (!raw || typeof raw !== "object") return null;
  const e = raw as RawEvent;
  if (typeof e.ref !== "string" || typeof e.ts !== "string" || !Number.isFinite(Date.parse(e.ts))) return null;
  return {
    ref: e.ref,
    log: typeof e.log === "string" ? e.log : "",
    ts: e.ts,
    description: typeof e.description === "string" ? e.description : e.ref,
    scope: e.scope && typeof e.scope === "object" ? (e.scope as Record<string, string[]>) : {},
  };
}

const num = (v: unknown) => (typeof v === "number" && Number.isFinite(v) ? v : null);

/**
 * The shop's logged changes the investigations looked at: planned events (`data.planned` of the calendar step,
 * with the plan's uplift and what was delivered) and other logged events (`data.events`: deploys, budget and
 * pacer changes). Deduplicated by ref; the first sighting wins, a later one adds a missing plan.
 */
function seenChanges(steps: readonly StepView[]): SeenChange[] {
  const out = new Map<string, SeenChange>();
  for (const s of steps) {
    if (s.step.tool !== "list_events") continue;
    const data = s.step.data ?? {};
    const planned = Array.isArray(data.planned) ? data.planned : [];
    for (const p of planned) {
      const ev = asEvent((p as { event?: unknown })?.event);
      if (!ev) continue;
      const rec = p as { uplift?: unknown; delivered?: unknown; status?: unknown };
      const prev = out.get(ev.ref);
      if (prev && prev.uplift !== null) continue;
      out.set(ev.ref, {
        ...ev,
        uplift: num(rec.uplift),
        delivered: num(rec.delivered),
        status: typeof rec.status === "string" ? rec.status : null,
        receipts: s.step.receipts,
      });
    }
    const events = Array.isArray(data.events) ? data.events : [];
    for (const raw of events) {
      const ev = asEvent(raw);
      if (!ev || out.has(ev.ref)) continue;
      out.set(ev.ref, { ...ev, uplift: null, delivered: null, status: null, receipts: s.step.receipts });
    }
  }
  return [...out.values()].sort((a, b) => a.ts.localeCompare(b.ts) || a.ref.localeCompare(b.ref));
}

/* ------------------------------------------------------------------ calendar */

export type Lane = "plan" | AgentRole;

export type EntryTone = "ok" | "watch" | "alarm" | "probe" | "calm" | "muted";

export interface CalendarEntry {
  id: string;
  lane: Lane;
  /** start, simulated time (ISO, no zone) */
  ts: string;
  title: string;
  detail: string;
  tone: EntryTone;
  receipts: string[];
  incident?: string;
  metric?: string;
  /** a planned event: what was planned, what was delivered, and the note that held its alert */
  plan?: { uplift: number | null; delivered: number | null; status: string | null; scope: Record<string, string[]>; log: string; note?: Note };
  /** a day's summary of many small runs (the watcher's hourly scoring, the cartographer's edge tests) */
  count?: number;
}

const day = (ts: string) => ts.slice(0, 10);

const LOG_KIND: Record<string, string> = {
  log_calendar: "Planned",
  log_ad_budgets: "Budget",
  log_deploys: "Deploy",
  log_provider_status: "Provider",
};

export function logLabel(log: string): string {
  return LOG_KIND[log] ?? "Logged";
}

/** The planned change a note names (note reason "planned change <ref> delivered ..."), if any. */
function noteRef(note: Note): string | null {
  if (note.kind !== "expected") return null;
  const m = /planned change (\S+)/.exec(note.reason);
  return m ? m[1] : null;
}

/**
 * Every entry of the calendar, folded from the run: the shop's logged changes the investigations looked at (the
 * plan lane), and per agent what it did when: the watcher's hourly scoring per day and the anomalies it opened,
 * the cartographer's edge tests per day, the detective's, skeptic's and market analyst's investigation steps per
 * anomaly, the narrator's incidents and held-back notes, the operator's proposals.
 */
export function calendarEntries(view: RunView, graph: Graph | null, proposals: readonly ProposalView[] = []): CalendarEntry[] {
  const out: CalendarEntry[] = [];
  const label = (id: string) => graph?.nodes.find((n) => n.id === id)?.label ?? id;

  for (const p of seenChanges(view.steps)) {
    const note = view.notes.find((n) => noteRef(n) === p.ref);
    const asPlanned = p.status === "as planned";
    out.push({
      id: `plan:${p.ref}`,
      lane: "plan",
      ts: p.ts,
      title: p.description,
      detail: `${logLabel(p.log)} change reviewed during an investigation.`,
      tone: p.uplift !== null ? (asPlanned ? "ok" : "watch") : "calm",
      receipts: [...new Set([...(note?.receipts ?? []), ...p.receipts])],
      plan: { uplift: p.uplift, delivered: p.delivered, status: p.status, scope: p.scope, log: p.log, note },
    });
  }

  // watcher: the hours it scored, one summary per day, and every anomaly it opened
  const hoursByDay = new Map<string, number>();
  for (const h of view.hours) hoursByDay.set(day(h.hour), (hoursByDay.get(day(h.hour)) ?? 0) + 1);
  for (const [d, n] of hoursByDay) {
    out.push({ id: `watch:${d}`, lane: "watcher", ts: `${d}T00:00:00`, title: `${n} hourly ${n === 1 ? "check" : "checks"}`, detail: "Scored every metric against the same hour of the last four weeks.", tone: "muted", receipts: [], count: n });
  }
  for (const a of view.anomalies) {
    out.push({
      id: `anomaly:${a.id}`,
      lane: "watcher",
      ts: a.detected_at,
      title: `${label(a.node)} ${a.direction === "up" ? "up" : "down"}`,
      detail: `Opened ${a.id}: observed ${a.observed.toFixed(2)} against ${a.expected.toFixed(2)} expected (z ${a.z.toFixed(1)}).`,
      tone: "watch",
      receipts: a.receipts,
      metric: a.node,
    });
  }

  // cartographer: edge tests, one summary per day
  const edgesByDay = new Map<string, { n: number; changed: number; first: string }>();
  for (const c of view.edgeChanges) {
    const d = day(c.simTs);
    const cur = edgesByDay.get(d) ?? { n: 0, changed: 0, first: c.simTs };
    cur.n += 1;
    if (c.from !== null && c.from !== c.to) cur.changed += 1;
    edgesByDay.set(d, cur);
  }
  for (const [d, e] of edgesByDay) {
    out.push({
      id: `edges:${d}`,
      lane: "cartographer",
      ts: e.first,
      title: `${e.n} formula ${e.n === 1 ? "test" : "tests"}`,
      detail: e.changed ? `${e.changed} changed status.` : "Every tested edge kept its status.",
      tone: e.changed ? "watch" : "muted",
      receipts: [],
      count: e.n,
    });
  }

  // detective, skeptic, market analyst, narrator: investigation steps grouped per anomaly and role
  const groups = new Map<string, { role: AgentRole; anomalyId: string; incidentId: string | null; first: string; steps: StepView[] }>();
  for (const s of view.steps) {
    const role = roleOfTool(s.step.tool, s.step.kind);
    const key = `${role}:${s.anomalyId}`;
    const g = groups.get(key) ?? { role, anomalyId: s.anomalyId, incidentId: s.incidentId, first: s.simTs, steps: [] };
    g.steps.push(s);
    g.incidentId = g.incidentId ?? s.incidentId;
    groups.set(key, g);
  }
  const anomalyNode = (id: string) => view.anomalies.find((a) => a.id === id)?.node;
  for (const g of groups.values()) {
    const node = anomalyNode(g.anomalyId);
    const what = node ? label(node) : g.anomalyId;
    const verdict = g.steps.find((s) => s.step.kind === "verdict");
    const refuted = g.steps.filter((s) => s.step.decision.toLowerCase().startsWith("refuted")).length;
    const title =
      g.role === "narrator" && verdict
        ? `Verdict on ${what}`
        : g.role === "skeptic"
          ? `Doubted ${what}`
          : g.role === "market"
            ? `Market check, ${what}`
            : g.role === "cartographer"
              ? `Followed ${what} down its formula`
              : g.role === "watcher"
                ? `Freshness check, ${what}`
                : `Investigated ${what}`;
    out.push({
      id: `steps:${g.role}:${g.anomalyId}`,
      lane: g.role,
      ts: g.first,
      title,
      detail: `${g.steps.length} ${g.steps.length === 1 ? "step" : "steps"}${refuted ? `, ${refuted} suspect${refuted === 1 ? "" : "s"} ruled out` : ""}.`,
      tone: g.role === "narrator" ? "ok" : "probe",
      receipts: [...new Set(g.steps.flatMap((s) => s.step.receipts))].slice(0, 8),
      incident: g.incidentId ?? undefined,
      metric: node,
    });
  }
  for (const s of view.skeptic) {
    const key = `steps:skeptic:${s.incident_id}`;
    if (out.some((e) => e.id === key)) continue;
    out.push({ id: key, lane: "skeptic", ts: s.incident_id ? (view.incidents[s.incident_id]?.openedAt ?? "") : "", title: `Challenged ${s.incident_id}`, detail: "Holdout and placebo checks against the verdict.", tone: "probe", receipts: [], incident: s.incident_id });
  }

  // narrator: incidents filed, and the alerts it held back
  for (const inc of Object.values(view.incidents)) {
    out.push({ id: `incident:${inc.id}`, lane: "narrator", ts: inc.openedAt, title: `Filed ${inc.id}`, detail: inc.title, tone: inc.state === "resolved" ? "ok" : "alarm", receipts: [], incident: inc.id, metric: inc.root_node });
  }
  for (const n of view.notes) {
    out.push({
      id: `note:${n.id}`,
      lane: n.kind === "expected" ? "skeptic" : "narrator",
      ts: n.sim_ts,
      title: n.kind === "expected" ? "Held back: planned" : n.kind === "data_issue" ? "Held back: late data" : "Held back",
      detail: n.reason,
      tone: "ok",
      receipts: n.receipts,
      metric: n.node ?? undefined,
    });
  }

  // operator: proposals the agent made
  for (const p of proposals) {
    out.push({ id: `action:${p.id}`, lane: "operator", ts: p.effective_at, title: p.action, detail: `${p.incident_ref}: ${p.state.toLowerCase().replace(/_/g, " ")}`, tone: p.state === "VERIFIED" ? "ok" : "watch", receipts: [], incident: p.incident_ref });
  }

  return out.filter((e) => e.ts).sort((a, b) => a.ts.localeCompare(b.ts) || a.id.localeCompare(b.id));
}

/** The seven days (Monday first) of the week that holds `ts`, as YYYY-MM-DD. */
export function weekOf(ts: string): string[] {
  const d = new Date(`${ts.slice(0, 10)}T00:00:00Z`);
  const monday = new Date(d);
  monday.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
  return Array.from({ length: 7 }, (_, i) => {
    const x = new Date(monday);
    x.setUTCDate(monday.getUTCDate() + i);
    return x.toISOString().slice(0, 10);
  });
}

export function shiftWeek(week: string[], by: number): string[] {
  const d = new Date(`${week[0]}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + 7 * by);
  return weekOf(d.toISOString());
}

export function segmentText(segment: Record<string, string[]>): string {
  const parts = Object.entries(segment).map(([k, v]) => `${k} ${v.join(", ")}`);
  return parts.length ? parts.join(" · ") : "whole shop";
}

/** Euro, queries, seconds and model calls the run's incidents report in their findings (Findings.cost). */
export function incidentCost(incidents: Incident[]): { eur: number; queries: number; seconds: number; llm_calls: number; n: number } {
  return incidents.reduce(
    (acc, i) => {
      const c = i.findings?.cost;
      if (!c) return acc;
      return { eur: acc.eur + c.eur, queries: acc.queries + c.queries, seconds: acc.seconds + c.seconds, llm_calls: acc.llm_calls + c.llm_calls, n: acc.n + 1 };
    },
    { eur: 0, queries: 0, seconds: 0, llm_calls: 0, n: 0 },
  );
}
