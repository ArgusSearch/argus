// Pure: a tape (C5 events, agent activity, proposals) to the village's beats. A beat is one thing one role does:
// what its bubble says while it works and after, the lines it adds to its tool log, and the case it holds.
// Numbers only appear as the API rendered them (step results, activity text); nothing here computes one.

import { segmentLabel } from "../lib/format";
import type { ArgusEvent, IncidentUpdatedPayload, TrailStep } from "../lib/types";
import type { RoleId } from "./roles";
import type { ActivityRecord, Decision, ProposalView, TapeIncident, TapePart, TapePlacement, VillageTape } from "./types";

export type Outcome = "ok" | "kept" | "refuted" | "alarm" | "info" | "wait" | "denied";

export interface LogEntry {
  /** stable within a tape: the C5 seq ("e12") or the activity seq ("a7") it came from */
  key: string;
  simTs: string;
  tool: string;
  title: string;
  detail: string | null;
  hypothesis: string | null;
  outcome: Outcome;
  receipts: string[];
}

export type BeatKind =
  | "watch"
  | "edges"
  | "detect"
  | "check"
  | "verdict"
  | "report"
  | "note"
  | "proposal"
  | "decision"
  | "apply"
  | "effect"
  | "lifecycle"
  | "chat";

export interface Beat {
  key: string;
  role: RoleId;
  kind: BeatKind;
  /** the case this beat works on (an anomaly or incident id); the orb follows it */
  caseId: string | null;
  simTs: string;
  /** the bubble while the beat plays */
  doing: string;
  /** the bubble once the beat is over and the role has moved on */
  done: string;
  outcome: Outcome;
  log: LogEntry[];
  /** relative length; the timeline turns it into seconds */
  weight: number;
  /** set on the beat that asks for your approval: the clock halts at its end until you decide */
  gate: { actionId: string | null; action: string; incidentId: string | null; proposal: ProposalView | null } | null;
}

const short = (text: string, max = 64) => {
  const t = text.replace(/\s+/g, " ").trim();
  return t.length > max ? `${t.slice(0, max - 1).trimEnd()}…` : t;
};

const label = (tape: Pick<VillageTape, "labels">, id: string | null | undefined) => (id ? (tape.labels[id] ?? id.replace(/_/g, " ")) : "");


// ---------------------------------------------------------------- C5 trail steps

/** Which role runs a check, by the tool the trail step names. Unknown tools belong to the Detective. */
export function roleOfTool(tool: string | null | undefined, kind?: string): RoleId {
  switch (tool) {
    case "check_freshness":
      return "watcher";
    case "check_identities":
      return "cartographer";
    case "decompose_formula":
      return kind === "impact" ? "narrator" : "cartographer";
    case "holdout_check":
    case "placebo_test":
    case "skeptic":
      return "skeptic";
    case "check_control_group":
    case "market_control":
      return "market";
    case "counterfactual_impact":
    case "verdict":
      return "narrator";
    case "propose_action":
      return "operator";
    default:
      return "detective";
  }
}

interface StepEvent {
  log?: string;
  ref?: string;
  description?: string;
  scope?: Record<string, string[]>;
}

/** The suspect a step tests: the logged event's description, else the hypothesis without its "caused the change". */
function suspectOf(step: TrailStep): string {
  const event = step.data?.event as StepEvent | undefined;
  if (event?.description) return event.description;
  return (step.hypothesis ?? "").replace(/\s*\([^)]*\)\s*caused the change\s*$/, "").replace(/\s*caused the change\s*$/, "");
}

function stepOutcome(step: TrailStep): Outcome {
  const d = step.decision.toLowerCase();
  if (d.startsWith("refuted")) return "refuted";
  if (d.startsWith("validated")) return "kept";
  if (step.kind === "verdict") return "ok";
  return "info";
}

function stepBeat(tape: VillageTape, seq: number, simTs: string, anomalyId: string, step: TrailStep, where: string): Beat {
  const role = roleOfTool(step.tool, step.kind);
  const outcome = stepOutcome(step);
  const suspect = suspectOf(step);
  const node = (step.data?.node as string | undefined) ?? null;
  let doing: string;
  let done: string;
  switch (step.tool) {
    case "check_freshness":
      doing = "Is every source table complete for this hour?";
      done = "Data is complete: the drop is real";
      break;
    case "check_identities":
      doing = "Do the metric formulas still add up?";
      done = "Every formula identity holds";
      break;
    case "list_events":
      doing = step.kind === "calendar" ? "Was anything planned for this hour?" : `What changed at that moment${where ? ` in ${where}` : ""}?`;
      done = step.kind === "calendar" ? "Nothing planned explains it" : short(step.decision.replace(/^test /, "Suspects to test: "));
      break;
    case "decompose_formula":
      doing = step.kind === "impact" ? "Sizing the damage along the formula" : `Following ${label(tape, node) || "the metric"} down its formula`;
      done = short(step.decision.charAt(0).toUpperCase() + step.decision.slice(1));
      break;
    case "mix_rate_split":
      doing = "Mix or rate? Splitting by country, platform, provider";
      done = short(step.decision.charAt(0).toUpperCase() + step.decision.slice(1));
      break;
    case "segment_search":
      doing = "Searching for the segment that carries the change";
      done = short(step.decision.charAt(0).toUpperCase() + step.decision.slice(1));
      break;
    case "get_series":
      doing = `When did it start${where ? ` in ${where}` : ""}?`;
      done = short(step.result.charAt(0).toUpperCase() + step.result.slice(1));
      break;
    case "holdout_check":
      doing = `Checking ${short(suspect, 44)}${where ? ` outside ${where}` : ""}…`;
      done = outcome === "refuted" ? `Ruled out: ${short(suspect, 46)}` : `Holds up: ${short(suspect, 48)}`;
      break;
    case "placebo_test":
      doing = "Placebo: were earlier weeks just as odd?";
      done = outcome === "kept" ? "No earlier week looks like this one" : short(step.result);
      break;
    case "check_control_group": {
      const market = step.data?.market_control as { verdict?: string } | undefined;
      doing = `Comparing ${label(tape, node) || "the shop"} with the market index`;
      done = market?.verdict === "market" ? "The whole market moved: expected" : market?.verdict === "us" ? "The market held up: this one is ours" : "The market comparison is inconclusive";
      break;
    }
    case "counterfactual_impact":
      doing = "What did it cost so far?";
      done = short(step.result);
      break;
    case "verdict":
      doing = "Writing the verdict";
      done = `Verdict: ${step.result.replace(/_/g, " ").toLowerCase()}`;
      break;
    default:
      doing = short(`Running ${step.tool.replace(/_/g, " ")}`);
      done = short(step.result);
  }
  return {
    key: `e${seq}`,
    role,
    kind: step.kind === "verdict" ? "verdict" : "check",
    caseId: anomalyId,
    simTs,
    doing,
    done,
    outcome,
    weight: step.kind === "verdict" ? 1.3 : step.tool === "holdout_check" ? 1.15 : 1,
    gate: null,
    log: [
      {
        key: `e${seq}`,
        simTs,
        tool: step.tool,
        title: `${step.step}. ${step.tool}`,
        detail: [step.result, step.decision && `→ ${step.decision}`].filter(Boolean).join(" "),
        hypothesis: step.hypothesis ?? null,
        outcome,
        receipts: step.receipts ?? [],
      },
    ],
  };
}

// ---------------------------------------------------------------- agent activity

function activityRole(rec: ActivityRecord): RoleId {
  switch (rec.kind) {
    case "watch":
      return "watcher";
    case "gate":
    case "rejected":
      return "skeptic";
    case "report":
    case "chat_question":
    case "chat_answer":
    case "run_finished":
      return "narrator";
    case "action_proposed":
    case "action_decided":
    case "action_applied":
    case "effect_checked":
      return "operator";
    case "run_started":
    case "budget":
    case "fallback":
      return "detective";
    default:
      return roleOfTool(rec.tool ?? rec.observation?.tool ?? null);
  }
}

function activityOutcome(rec: ActivityRecord): Outcome {
  const o = rec.observation?.outcome ?? "";
  if (o === "refuted") return "refuted";
  if (o === "confirmed" || o === "consistent" || o === "supported") return "kept";
  if (rec.kind === "rejected" || rec.kind === "fallback") return "alarm";
  if (rec.kind === "action_proposed") return "wait";
  if (rec.kind === "effect_checked") return /no_effect|inconclusive/i.test(rec.text) ? "alarm" : "ok";
  return "info";
}

function activityBeat(rec: ActivityRecord, actions: ProposalView[], live: boolean, caseId: string | null): Beat | null {
  const role = activityRole(rec);
  const outcome = activityOutcome(rec);
  const tool = rec.tool ?? rec.observation?.tool ?? rec.kind;
  const text = rec.text || rec.observation?.summary || "";
  const log: LogEntry = {
    key: `a${rec.seq}`,
    simTs: rec.sim_ts,
    tool,
    title: rec.kind === "tool_call" || rec.kind === "tool_result" ? `${rec.kind === "tool_call" ? "call" : "result"} · ${tool}` : rec.kind.replace(/_/g, " "),
    detail: text || null,
    hypothesis: rec.observation?.hypothesis ?? (typeof rec.args?.hypothesis === "string" ? (rec.args.hypothesis as string) : null),
    outcome,
    receipts: (rec.receipt_links ?? []).map((r) => r.receipt_id),
  };
  const base: Pick<Beat, "key" | "role" | "caseId" | "simTs" | "outcome" | "log" | "gate" | "weight"> = { key: `a${rec.seq}`, role, caseId, simTs: rec.sim_ts, outcome, log: [log], gate: null, weight: 1 };
  switch (rec.kind) {
    case "watch":
      return { ...base, kind: "watch", doing: short(text || "Scoring this hour"), done: short(text || "A quiet hour"), weight: 0.45 };
    case "run_started":
      return { ...base, kind: "check", doing: "Opening the case", done: short(text || "Case opened") };
    case "thought":
      return { ...base, kind: "check", doing: short(text), done: short(text), weight: 0.8 };
    case "tool_call":
      return { ...base, kind: "check", doing: short(`${rec.observation?.hypothesis ? `Checking: ${rec.observation.hypothesis}` : text || `Running ${tool.replace(/_/g, " ")}`}…`), done: short(text || tool) };
    case "tool_result":
      return {
        ...base,
        kind: "check",
        doing: short(text || "Reading the result"),
        done: outcome === "refuted" ? short(`Ruled out: ${rec.observation?.hypothesis ?? text}`) : short(text || "Result in"),
        weight: 0.9,
      };
    case "gate":
      return { ...base, kind: "check", doing: "Does the evidence carry the verdict?", done: short(text || "The gate decided") };
    case "rejected":
      return { ...base, kind: "check", doing: "Sending a draft back", done: short(`Sent back: ${text}`) };
    case "report":
      return { ...base, kind: "report", doing: "Writing the report", done: short(text || "Report filed"), weight: 1.3 };
    case "action_proposed": {
      const proposal = actions.find((a) => a.id === rec.action_id) ?? null;
      const action = proposal?.action ?? text;
      return {
        ...base,
        kind: "proposal",
        doing: short(action, 70),
        done: short(`Proposed: ${action}`),
        weight: 1.2,
        gate: !live || proposal?.state === "AWAIT_OPERATOR" ? { actionId: rec.action_id ?? null, action, incidentId: rec.incident_id ?? null, proposal } : null,
      };
    }
    case "action_decided":
      return { ...base, kind: "decision", doing: short(text || "Decision saved"), done: short(text || "Decision saved") };
    case "action_applied":
      return { ...base, kind: "apply", doing: short(text || "Applying the approved action"), done: short(text || "Action applied"), weight: 1.4 };
    case "effect_checked":
      return { ...base, kind: "effect", doing: "Checking the effect against an untouched twin", done: short(text || "Effect checked", 96), weight: 1.4 };
    case "budget":
    case "fallback":
      return { ...base, kind: "check", doing: short(text || rec.kind), done: short(text || rec.kind) };
    case "chat_question":
    case "chat_answer":
      return { ...base, kind: "chat", doing: short(text), done: short(text) };
    case "run_finished":
      return { ...base, kind: "report", doing: "Closing the run", done: short(text || "Run finished"), weight: 0.6 };
    default:
      return null;
  }
}

// ---------------------------------------------------------------- a new metric places itself

const EDGE_LINE = /^([fbc]_[a-z0-9_]+) \[(\w+)\] (.*?) -> (accepted|rejected|probation|proposed)?:? ?(.*)$/;

/** The beats of one placement: the Cartographer reads the SQL, searches the map, the Skeptic screens for mere
 * correlations, the Cartographer tests every proposed edge, then places, holds or rejects the metric. */
export function placementBeats(p: TapePlacement, index: number): Beat[] {
  const name = p.metric.name;
  const at = p.as_of;
  const key = (k: string) => `m${index}:${k}`;
  const entry = (k: string, tool: string, title: string, detail: string | null, outcome: Outcome): LogEntry => ({
    key: key(k),
    simTs: at,
    tool,
    title,
    detail,
    hypothesis: null,
    outcome,
    receipts: [],
  });
  const lines = (prefix: string) => p.tried.filter((t) => t.startsWith(prefix));
  const edges = p.tried.filter((t) => EDGE_LINE.test(t));
  const beats: Beat[] = [];
  const beat = (k: string, role: RoleId, kind: BeatKind, doing: string, done: string, outcome: Outcome, log: LogEntry[], weight = 1): void => {
    beats.push({ key: key(k), role, kind, caseId: name, simTs: at, doing: short(doing), done: short(done), outcome, log, weight, gate: null });
  };
  const read = [...lines("lineage:"), ...lines("definition check:"), ...lines("fan-out guard:")];
  beat(
    "read",
    "cartographer",
    "check",
    `New metric to place: ${name}`,
    read.some((t) => t.startsWith("fan-out")) ? "Its SQL joins tables below their keys" : `Read its SQL: ${(lines("lineage:")[0] ?? "").replace(/^lineage: /, "").split(";")[0]}`,
    "info",
    [entry("intro", "propose_metric", name, p.metric.description, "info"), ...read.map((t, i) => entry(`r${i}`, t.split(":")[0].replace(/ /g, "_"), t.split(":")[0], t.slice(t.indexOf(":") + 1).trim(), t.startsWith("fan-out") ? "alarm" : "ok"))],
    1.2,
  );
  if (p.placed_as === "REJECTED") {
    beat("verdict", "cartographer", "verdict", `Can ${name} be placed?`, `Rejected: ${p.summary.split(":")[0]}`, "alarm", [entry("v", "place_metric", `${name} rejected`, p.summary, "alarm")], 1.4);
    return beats;
  }
  const search = [...lines("numeric alias:"), ...lines("arithmetic search:")];
  if (search.length)
    beat("search", "cartographer", "check", "Is it something the map already has?", "Nothing in the map has the same numbers", "ok", search.map((t, i) => entry(`s${i}`, t.split(":")[0].replace(/ /g, "_"), t.split(":")[0], t.slice(t.indexOf(":") + 1).trim(), "ok")));
  const scan = lines("correlation scan:");
  if (scan.length) {
    const kept = /kept (\d+)/.exec(scan[0])?.[1] ?? "0";
    beat(
      "scan",
      "skeptic",
      "check",
      "Correlated is not causal: screening hidden links",
      kept === "0" ? "No link survives the screen" : `${kept} link kept on probation, correlated only`,
      kept === "0" ? "ok" : "info",
      scan.map((t, i) => entry(`c${i}`, "correlation_scan", "correlation scan", t.replace(/^correlation scan: /, ""), "ok")),
    );
  }
  if (edges.length) {
    const ok = edges.filter((t) => / -> accepted/.test(t)).length;
    beat(
      "edges",
      "cartographer",
      "edges",
      `Testing ${edges.length} new edge${edges.length === 1 ? "" : "s"} of ${name}`,
      `${ok} of ${edges.length} edges hold`,
      ok === edges.length ? "ok" : "info",
      edges.map((t, i) => {
        const m = EDGE_LINE.exec(t);
        return entry(`e${i}`, "edge_test", m ? m[3] : t, m ? `${m[4] ?? ""} ${m[5]}`.trim() : null, m?.[4] === "accepted" ? "ok" : "info");
      }),
      1.3,
    );
  }
  const formula = p.summary.split(" (")[0];
  if (p.placed_as === "AMBIGUOUS")
    beat("verdict", "cartographer", "verdict", `Where does ${name} belong?`, "Held: two formulas fit equally well, so it stays proposed", "info", [entry("v", "place_metric", `${name} held`, [p.summary, ...p.uncertain].join(" · "), "info")], 1.4);
  else beat("verdict", "cartographer", "verdict", `Placing ${name} in the map`, `Placed: ${formula}`, "ok", [entry("v", "place_metric", `${name} placed (${p.placed_as})`, p.summary, "ok")], 1.4);
  return beats;
}

// ---------------------------------------------------------------- the whole tape

const CASE_TYPES = new Set(["anomaly_opened", "investigation_step", "skeptic_step", "incident_updated", "note_logged"]);

interface Ordered {
  ts: string;
  /** 0: watch-side C5 before activity at the same hour, 1: activity, 2: case-side C5 */
  lane: number;
  seq: number;
  event?: ArgusEvent;
  record?: ActivityRecord;
}

function ordered(part: TapePart): Ordered[] {
  const agentCases = new Set(part.activity.map((record) => record.anomaly_id));
  const items: Ordered[] = [
    ...part.events.map((event) => {
      const startsAgent = event.type === "anomaly_opened" && agentCases.has(event.payload.id);
      return { ts: event.sim_ts, lane: !startsAgent && CASE_TYPES.has(event.type) ? 2 : 0, seq: event.seq, event };
    }),
    ...part.activity.map((record) => ({ ts: record.sim_ts, lane: 1, seq: record.seq, record })),
  ];
  return items.sort((a, b) => (a.ts < b.ts ? -1 : a.ts > b.ts ? 1 : a.lane - b.lane || a.seq - b.seq));
}

function lifecycleText(p: IncidentUpdatedPayload): { role: RoleId; doing: string; done: string; outcome: Outcome } | null {
  if (p.state === "monitoring") return { role: "watcher", doing: `${p.id} is back inside its band: keep watching`, done: `${p.id} recovering, watching before closing`, outcome: "ok" };
  if (p.state === "resolved") return { role: "watcher", doing: `Closing ${p.id}: normal hours in a row`, done: `${p.id} closed`, outcome: "ok" };
  if (p.change === "reopened") return { role: "watcher", doing: `${p.id} broke again: reopening`, done: `${p.id} reopened`, outcome: "alarm" };
  return null;
}

function hourOf(ts: string): string {
  return ts.slice(11, 16);
}

export interface BuildOptions {
  /** the operator's decision on the gate, or null while nobody decided */
  decision: Decision | null;
  /** quiet hours shown one by one before an anomaly; earlier ones are folded into one beat */
  leadHours?: number;
}

/**
 * The beats of a tape. With no decision the beats stop at the first approval gate (the clock halts there);
 * with one, the decision, the chosen continuation and the rest of the tape follow.
 */
export function buildBeats(tape: VillageTape, opts: BuildOptions): Beat[] {
  const lead = opts.leadHours ?? 3;
  const incidents = new Map<string, TapeIncident>(tape.incidents.map((i) => [i.id, i]));
  const agentRuns = new Set(tape.activity.filter((r) => r.anomaly_id).map((r) => r.anomaly_id as string));
  const caseOfRun = new Map<string, string>();
  for (const record of tape.activity) {
    if (record.run_id && record.anomaly_id) caseOfRun.set(record.run_id, record.anomaly_id);
  }
  const beats: Beat[] = [];
  const where = new Map<string, string>(); // anomaly id -> located segment, for the bubbles
  const caseOfIncident = new Map<string, string>();
  let quiet: Extract<ArgusEvent, { type: "tick" }>[] = [];
  let edges: Extract<ArgusEvent, { type: "edge_status" }>[] = [];
  let gated = false;
  let gateAsked = false;

  const flushEdges = () => {
    if (!edges.length) return;
    const first = edges[0];
    const changed = edges.filter((e) => e.payload.old_status !== null && e.payload.old_status !== e.payload.new_status);
    const broken = edges.filter((e) => e.payload.new_status === "BROKEN");
    const initial = edges.every((e) => e.payload.old_status === null);
    beats.push({
      key: `e${first.seq}`,
      role: "cartographer",
      kind: "edges",
      caseId: null,
      simTs: first.sim_ts,
      doing: initial ? `Testing ${edges.length} formula edges of the metric map` : `Re-testing ${edges.length} formula edge${edges.length === 1 ? "" : "s"}`,
      done: broken.length
        ? `${broken.length} edge${broken.length === 1 ? "" : "s"} broke: the map is flagged`
        : changed.length
          ? `${changed.length} edge${changed.length === 1 ? "" : "s"} changed status`
          : `All ${edges.length} formula edges hold`,
      outcome: broken.length ? "alarm" : "ok",
      weight: 1.4,
      gate: null,
      log: edges.map((e) => ({
        key: `e${e.seq}`,
        simTs: e.sim_ts,
        tool: "edge_test",
        title: `edge ${e.payload.edge}`,
        detail: `${e.payload.old_status ?? "new"} → ${e.payload.new_status}${e.payload.result.hours ? ` over ${e.payload.result.hours} h` : ""}${e.payload.result.note ? `: ${e.payload.result.note}` : ""}`,
        hypothesis: null,
        outcome: e.payload.new_status === "BROKEN" ? "alarm" : "ok",
        receipts: e.payload.result.receipts ?? [],
      })),
    });
    edges = [];
  };

  const flushQuiet = (keep: number) => {
    if (!quiet.length) return;
    const shown = keep > 0 ? quiet.slice(-keep) : [];
    const folded = quiet.slice(0, quiet.length - shown.length);
    const tickLog = (t: (typeof quiet)[number]): LogEntry => {
      const zs = Object.entries(t.payload.max_abs_z ?? {});
      const top = zs.sort((a, b) => b[1] - a[1])[0];
      return {
        key: `e${t.seq}`,
        simTs: t.sim_ts,
        tool: "score_hour",
        title: `hour ${hourOf(t.payload.hour)}`,
        detail: `${t.payload.scored_nodes.length} series scored${top ? `, largest |z| ${top[1].toFixed(1)} on ${label(tape, top[0])}` : ""}`,
        hypothesis: null,
        outcome: "ok",
        receipts: [],
      };
    };
    if (folded.length) {
      beats.push({
        key: `e${folded[0].seq}`,
        role: "watcher",
        kind: "watch",
        caseId: null,
        simTs: folded[folded.length - 1].sim_ts,
        doing: `Scoring every metric, hour after hour`,
        done: `${folded.length} quiet hour${folded.length === 1 ? "" : "s"} watched, all inside their bands`,
        outcome: "ok",
        weight: 1.2,
        gate: null,
        log: folded.map(tickLog),
      });
    }
    for (const t of shown) {
      beats.push({
        key: `e${t.seq}`,
        role: "watcher",
        kind: "watch",
        caseId: null,
        simTs: t.sim_ts,
        doing: `Scoring the ${hourOf(t.payload.hour)} hour…`,
        done: `${hourOf(t.payload.hour)}: all inside their bands`,
        outcome: "ok",
        weight: 0.55,
        gate: null,
        log: [tickLog(t)],
      });
    }
    quiet = [];
  };

  const askApproval = (incidentId: string, caseId: string | null, simTs: string) => {
    if (tape.scenario === "live") return;
    const action = incidents.get(incidentId)?.suggested_action;
    if (!action?.needs_approval || gateAsked) return;
    gateAsked = true;
    beats.push({
      key: `g${incidentId}`,
      role: "operator",
      kind: "proposal",
      caseId,
      simTs,
      doing: short(action.text.replace(/ and watch [a-z_]+\.?$/, "").replace(/country /g, ""), 70),
      done: short(`Proposed: ${action.text}`),
      outcome: "wait",
      weight: 1.2,
      gate: { actionId: null, action: action.text, incidentId, proposal: null },
      log: [
        {
          key: `g${incidentId}`,
          simTs,
          tool: "propose_action",
          title: `proposal for ${incidentId}`,
          detail: action.text,
          hypothesis: null,
          outcome: "wait",
          receipts: [],
        },
      ],
    });
  };

  const visit = (items: Ordered[]): boolean => {
    for (const item of items) {
      if (gated) return false;
      if (item.record) {
        const rec = item.record;
        if (rec.gate_action && opts.decision !== "approve") continue;
        if (rec.kind === "watch") {
          flushEdges();
        } else {
          flushEdges();
          flushQuiet(lead);
        }
        const caseId = rec.anomaly_id ?? (rec.run_id ? caseOfRun.get(rec.run_id) : undefined) ?? rec.incident_id ?? null;
        if (caseId && rec.incident_id) caseOfIncident.set(rec.incident_id, caseId);
        const beat = activityBeat(rec, tape.actions, tape.scenario === "live", caseId);
        if (!beat) continue;
        beats.push(beat);
        if (beat.gate) {
          gateAsked = true;
          if (!opts.decision) {
            gated = true;
            return false;
          }
          const cont = tape.continuations[opts.decision];
          const released = tape.activity.some((r) => r.gate_action && r.gate_action === beat.gate?.actionId);
          if (!cont?.activity.some((record) => record.kind === "action_decided" && record.action_id === beat.gate?.actionId)) {
            beats.push(decisionBeat(beat, opts.decision, Boolean(cont?.activity.length || cont?.events.length || released)));
          }
        }
        continue;
      }
      const event = item.event as ArgusEvent;
      switch (event.type) {
        case "tick":
          flushEdges();
          quiet.push(event);
          break;
        case "edge_status":
          if (edges.length && edges[edges.length - 1].sim_ts !== event.sim_ts) flushEdges();
          edges.push(event);
          break;
        case "graph_changed":
          flushEdges();
          beats.push({
            key: `e${event.seq}`,
            role: "cartographer",
            kind: "edges",
            caseId: null,
            simTs: event.sim_ts,
            doing: short(`Updating the map: ${event.payload.reason || event.payload.kind}`),
            done: short(`Map updated: ${event.payload.node ? label(tape, event.payload.node) : (event.payload.edge ?? event.payload.kind)}`),
            outcome: "info",
            weight: 1,
            gate: null,
            log: [
              {
                key: `e${event.seq}`,
                simTs: event.sim_ts,
                tool: "graph_change",
                title: event.payload.kind.replace(/_/g, " "),
                detail: event.payload.reason,
                hypothesis: null,
                outcome: "info",
                receipts: event.payload.receipts ?? [],
              },
            ],
          });
          break;
        case "anomaly_opened": {
          flushEdges();
          flushQuiet(lead);
          const a = event.payload;
          beats.push({
            key: `e${event.seq}`,
            role: "watcher",
            kind: "detect",
            caseId: a.id,
            simTs: event.sim_ts,
            doing: short(`${label(tape, a.node)} left its band (z ${a.z > 0 ? "+" : ""}${a.z.toFixed(1)}): opening a case`),
            done: short(`Raised ${a.id}: ${label(tape, a.node)} ${a.direction}`),
            outcome: "alarm",
            weight: 1.5,
            gate: null,
            log: [
              {
                key: `e${event.seq}`,
                simTs: event.sim_ts,
                tool: "detect",
                title: `${a.id} · ${a.node}`,
                detail: `${a.direction} at ${hourOf(a.hour)}, z ${a.z > 0 ? "+" : ""}${a.z.toFixed(2)}, rule ${a.rule}${Object.keys(a.segment).length ? ` in ${segmentLabel(a.segment)}` : ""}`,
                hypothesis: null,
                outcome: "alarm",
                receipts: a.receipts ?? [],
              },
            ],
          });
          break;
        }
        case "investigation_step": {
          if (agentRuns.has(event.payload.anomaly_id) && event.payload.step.kind !== "verdict") break;
          flushEdges();
          flushQuiet(lead);
          const { anomaly_id, incident_id, step } = event.payload;
          if (step.tool === "segment_search" && /^root segment /.test(step.decision)) {
            where.set(anomaly_id, step.decision.replace(/^root segment /, "").replace(/ \/ /g, " · "));
          }
          if (incident_id) caseOfIncident.set(incident_id, anomaly_id);
          beats.push(stepBeat(tape, event.seq, event.sim_ts, anomaly_id, step, where.get(anomaly_id) ?? ""));
          break;
        }
        case "skeptic_step": {
          flushQuiet(lead);
          const p = event.payload;
          beats.push({
            key: `e${event.seq}`,
            role: "skeptic",
            kind: "check",
            caseId: caseOfIncident.get(p.incident_id) ?? p.incident_id,
            simTs: event.sim_ts,
            doing: short(`Doubting the verdict: ${p.check}`),
            done: short(p.result),
            outcome: /refut|weak/i.test(p.result) ? "refuted" : "kept",
            weight: 1,
            gate: null,
            log: [
              { key: `e${event.seq}`, simTs: event.sim_ts, tool: "skeptic", title: p.check, detail: p.result, hypothesis: null, outcome: "info", receipts: p.receipts ?? [] },
            ],
          });
          break;
        }
        case "incident_updated": {
          flushQuiet(lead);
          const p = event.payload;
          const caseId = caseOfIncident.get(p.id) ?? p.id;
          caseOfIncident.set(p.id, caseId);
          const life = lifecycleText(p);
          if (life) {
            beats.push({
              key: `e${event.seq}`,
              role: life.role,
              kind: "lifecycle",
              caseId,
              simTs: event.sim_ts,
              doing: short(life.doing),
              done: short(life.done),
              outcome: life.outcome,
              weight: 1.2,
              gate: null,
              log: [
                { key: `e${event.seq}`, simTs: event.sim_ts, tool: "incident", title: `${p.id} → ${p.state}`, detail: p.reason, hypothesis: null, outcome: life.outcome, receipts: [] },
              ],
            });
            break;
          }
          beats.push({
            key: `e${event.seq}`,
            role: "narrator",
            kind: "report",
            caseId,
            simTs: event.sim_ts,
            doing: `Filing ${p.id} with its receipts`,
            done: short(`Filed ${p.id}: ${p.title.split(":")[0]}`),
            outcome: "ok",
            weight: 1.4,
            gate: null,
            log: [
              {
                key: `e${event.seq}`,
                simTs: event.sim_ts,
                tool: "file_incident",
                title: `${p.id} ${p.change} · ${p.state}`,
                detail: `${p.title}${Object.keys(p.segment).length ? ` (${segmentLabel(p.segment)})` : ""}`,
                hypothesis: null,
                outcome: "ok",
                receipts: [],
              },
            ],
          });
          if (p.verdict !== "UNEXPLAINED" && (p.state === "explained" || p.state === "investigating")) {
            if (!tape.activity.some((r) => r.kind === "action_proposed")) askApproval(p.id, caseId, event.sim_ts);
            if (gateAsked && !opts.decision) {
              gated = true;
              return false;
            }
            if (gateAsked && beats[beats.length - 1].gate) {
              const cont = opts.decision ? tape.continuations[opts.decision] : undefined;
              beats.push(decisionBeat(beats[beats.length - 1], opts.decision as Decision, Boolean(cont?.activity.length || cont?.events.length)));
            }
          }
          break;
        }
        case "note_logged": {
          flushQuiet(lead);
          const n = event.payload;
          const kind = n.kind === "expected" ? "Planned or market-wide: logged, nobody woken" : n.kind === "data_issue" ? "Late data: holding the alert" : "Knock-on effect of an open incident";
          beats.push({
            key: `e${event.seq}`,
            role: "narrator",
            kind: "note",
            caseId: null,
            simTs: event.sim_ts,
            doing: short(`${label(tape, n.node)}: ${kind}`),
            done: short(kind),
            outcome: "info",
            weight: 1,
            gate: null,
            log: [{ key: `e${event.seq}`, simTs: event.sim_ts, tool: `note_${n.kind}`, title: label(tape, n.node) || n.id, detail: n.reason, hypothesis: null, outcome: "info", receipts: n.receipts ?? [] }],
          });
          break;
        }
        default:
          break;
      }
    }
    return true;
  };

  // a decision's continuation extends the whole prefix (lane D's presentation layout)
  if (visit(ordered(tape)) && opts.decision && gateAsked) {
    const cont = tape.continuations[opts.decision];
    if (cont) visit(ordered(cont));
  }
  if (!gated) {
    flushEdges();
    // the quiet hours after the story: one beat, the village goes back to watching
    flushQuiet(0);
    (tape.placements ?? []).forEach((p, i) => beats.push(...placementBeats(p, i)));
  }
  return beats;
}

/** The beat that records your decision at the Operator's igloo. `recorded` is false on a C5-only tape. */
function decisionBeat(gate: Beat, decision: Decision, recorded: boolean): Beat {
  const action = gate.gate?.action ?? "the action";
  const approved = decision === "approve";
  const doing = approved ? `Approved by you: ${action}` : `Denied by you: ${action}`;
  const done = approved
    ? recorded
      ? "Approved: applying in the simulator"
      : "Approved. This historical investigation has no action to apply, so nothing runs"
    : "Denied: nothing is changed";
  return {
    key: `${gate.key}:${decision}`,
    role: "operator",
    kind: "decision",
    caseId: gate.caseId,
    simTs: gate.simTs,
    doing: short(doing, 90),
    done,
    outcome: approved ? "ok" : "denied",
    weight: 1.2,
    gate: null,
    log: [
      {
        key: `${gate.key}:${decision}`,
        simTs: gate.simTs,
        tool: "operator_decision",
        title: approved ? "approved by operator" : "denied by operator",
        detail: approved && !recorded ? `${action} (historical result has no execution evidence)` : action,
        hypothesis: null,
        outcome: approved ? "ok" : "denied",
        receipts: [],
      },
    ],
  };
}

/** True when the tape asks for an approval somewhere. */
export function hasGate(tape: VillageTape): boolean {
  return buildBeats(tape, { decision: "approve" }).some((b) => b.gate);
}
