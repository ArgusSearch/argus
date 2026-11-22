// The agent's work log, grouped by run (pattern from T3 Code's TimelineWorkGroupRows and TimelinePendingApprovalRow,
// pingdotgg/t3code, MIT; rewritten for Argus): each run is one disclosure whose header reads as one line ("Ran 3
// checks: 2 confirmed, 1 ruled out"), the running one shows what it is doing now and for how long, and a proposal
// waiting for a person stays in view inside its run, folded or not, with its approve and deny right there.

import "./agent-ui.css";
import { memo } from "react";
import { AgentReceiptChips } from "../components/Receipts";
import { roleOf, type ActivityKind, type ActivityRecord, type ProposalView } from "../lib/agent";
import { hhmm, humanize } from "../lib/format";
import { Proposal } from "../fx/workspace/ActionCard";
import { AvatarSlot } from "../fx/workspace/AvatarSlot";
import { VERDICT, type Tone } from "../fx/workspace/plain";
import { Pill } from "../fx/workspace/ui";
import { openIncidentPage } from "../fx/nav";
import {
  gateOf,
  groupSummary,
  GROUP_TITLE,
  liveLine,
  outcomeTone,
  proposalsOf,
  usdOf,
  type CheckStep,
  type RunGroup,
  type Step,
} from "./activity";
import { Elapsed } from "./hooks";

const KIND: Record<ActivityKind, { word: string; tone: Tone }> = {
  run_started: { word: "Started", tone: "muted" },
  thought: { word: "Thinks", tone: "probe" },
  tool_call: { word: "Runs a check", tone: "probe" },
  tool_result: { word: "Result", tone: "muted" },
  gate: { word: "Verdict gate", tone: "watch" },
  report: { word: "Report", tone: "ok" },
  rejected: { word: "Sent back", tone: "alarm" },
  action_proposed: { word: "Proposes", tone: "probe" },
  action_decided: { word: "You decided", tone: "ok" },
  action_applied: { word: "Applied", tone: "watch" },
  effect_checked: { word: "Effect checked", tone: "ok" },
  budget: { word: "Budget", tone: "watch" },
  fallback: { word: "Fixed checklist took over", tone: "watch" },
  chat_question: { word: "You asked", tone: "muted" },
  chat_answer: { word: "Answer", tone: "ok" },
  watch: { word: "Quiet hour", tone: "muted" },
  run_finished: { word: "Finished", tone: "muted" },
};

const STATUS_WORD: Record<string, { word: string; tone: Tone }> = {
  budget: { word: "stopped at its budget", tone: "watch" },
  failed: { word: "failed", tone: "alarm" },
  fallback: { word: "handed to the fixed checklist", tone: "watch" },
};

/** the lines that name an incident with a link; the rest of a run is about the same incident */
const LINKED = new Set<ActivityKind>(["run_started", "report", "action_proposed", "effect_checked"]);

export const usd = (n: number) => `$${n < 0.1 ? n.toFixed(3) : n.toFixed(2)}`;
const verdictWord = (code: string) => VERDICT[code as keyof typeof VERDICT]?.label ?? humanize(code.toLowerCase());

function Who({ actor }: { actor: ActivityRecord["actor"] }) {
  return (
    <span className={`ag-who ${actor}`} title={actor === "model" ? "the language model wrote this" : actor === "host" ? "Argus' own code ran this" : "a person did this"}>
      {actor === "model" ? "AI" : actor === "host" ? "Argus" : "You"}
    </span>
  );
}

function ModelCost({ r }: { r: ActivityRecord }) {
  if (!r.model) return null;
  return (
    <span className="mono">
      {r.model} · {r.input_tokens ?? 0} in / {r.output_tokens ?? 0} out{r.usd !== null ? ` · ${usd(r.usd)}` : ""}
    </span>
  );
}

/** A check and its result as one row: what was suspected, what would follow, what came back. */
export const CheckRow = memo(function CheckRow({ check, time = true }: { check: CheckStep; time?: boolean }) {
  const { call, result } = check;
  const o = call?.observation ?? result?.observation ?? null;
  const outcome = result?.observation?.outcome ?? null;
  const at = (call ?? result) as ActivityRecord;
  const running = !result;
  const links = result ? (result.receipt_links.length ? result.receipt_links : (result.observation?.receipt_refs ?? [])) : [];
  return (
    <li className={`au-step au-check${running ? " running" : ""}`}>
      {time && <span className="ag-time mono">{hhmm(at.sim_ts)}</span>}
      <AvatarSlot role={check.role} size="md" nameplate status={running ? "working" : undefined} />
      <div className="ag-body">
        <span className="ag-kind">
          <Pill tone="probe">Check</Pill>
          <span className="mono au-tool">{check.tool}</span>
          {outcome ? <Pill tone={outcomeTone(outcome)}>{humanize(outcome)}</Pill> : running && <span className="au-running">running</span>}
        </span>
        {call?.text && call.text !== o?.prediction && <p className="ag-text">{call.text}</p>}
        {o && (o.hypothesis || o.prediction) && (
          <p className="ag-pred">
            {o.hypothesis && (
              <>
                <span>Suspect</span>
                {o.hypothesis}
              </>
            )}
            {o.prediction && (
              <>
                <span>If so, then</span>
                {o.prediction}
              </>
            )}
          </p>
        )}
        {result && (result.text || result.observation?.summary) && <p className="ag-text au-result">{result.text || result.observation?.summary}</p>}
        {(links.length > 0 || call?.model) && (
          <span className="ag-meta">
            <AgentReceiptChips links={links} />
            {call && <ModelCost r={call} />}
          </span>
        )}
      </div>
    </li>
  );
});

/** Any other step: what the model said, what the gate did, what was proposed or decided. */
function RecordRow({ r, proposal }: { r: ActivityRecord; proposal: ProposalView | null }) {
  const k = KIND[r.kind];
  if (r.kind === "action_proposed" && proposal) return <ApprovalRow proposal={proposal} at={r.sim_ts} />;
  return (
    <li className={`au-step k-${r.kind}`}>
      <span className="ag-time mono">{hhmm(r.sim_ts)}</span>
      <AvatarSlot role={roleOf(r)} size="md" nameplate status={r.kind === "rejected" || r.kind === "fallback" ? "alarm" : undefined} />
      <div className="ag-body">
        <span className="ag-kind">
          <Who actor={r.actor} />
          <Pill tone={k.tone}>{k.word}</Pill>
          {r.tool && <span className="mono au-tool">{r.tool}</span>}
        </span>
        {r.text && <p className="ag-text">{r.text}</p>}
        {(r.receipt_links.length > 0 || r.model || (r.incident_id && LINKED.has(r.kind))) && (
          <span className="ag-meta">
            <AgentReceiptChips links={r.receipt_links} />
            <ModelCost r={r} />
            {r.incident_id && LINKED.has(r.kind) && (
              <button className="ag-link" onClick={() => openIncidentPage(r.incident_id as string)}>
                {r.incident_id}
              </button>
            )}
          </span>
        )}
      </div>
    </li>
  );
}

/** A proposal inside the log: waiting ones say so and carry their two buttons, bound to the digest seen. */
export function ApprovalRow({ proposal, at }: { proposal: ProposalView; at?: string }) {
  const waiting = proposal.state === "AWAIT_OPERATOR";
  return (
    <li className={`au-step au-approval${waiting ? " waiting" : ""}`} role="group" aria-label={waiting ? "Proposal waiting for your decision" : "Proposal"}>
      <span className="ag-time mono">{at ? hhmm(at) : ""}</span>
      <span className="au-approval-mark" aria-hidden="true">
        <svg viewBox="0 0 16 16">
          <path d="M8 1.8l5.2 2v4.1c0 3.1-2.2 5.3-5.2 6.3c-3-1-5.2-3.2-5.2-6.3v-4.1z" />
        </svg>
      </span>
      <div className="ag-body">
        <Proposal proposal={proposal} compact />
      </div>
    </li>
  );
}

function StepRow({ step, proposals }: { step: Step; proposals: ProposalView[] }) {
  if (step.kind === "check") return <CheckRow check={step} />;
  const r = step.record;
  const proposal = r.kind === "action_proposed" ? (proposals.find((p) => p.id === r.action_id) ?? null) : null;
  return <RecordRow r={r} proposal={proposal} />;
}

/** The faces of the roles that worked on a run, overlapping like a group chat's avatars. */
function Faces({ group, live }: { group: RunGroup; live: boolean }) {
  const roles = group.roles.slice(0, 4);
  return (
    <span className="au-faces" aria-hidden="true">
      {roles.map((role, i) => (
        <AvatarSlot key={role} role={role} size="sm" status={live && i === roles.length - 1 ? "working" : undefined} />
      ))}
    </span>
  );
}

/** What the live run is doing now, shimmering, with how long it has worked. */
function LiveRow({ group, clockId }: { group: RunGroup; clockId: string }) {
  const now = liveLine(group);
  return (
    <div className="au-live" aria-live="polite">
      <AvatarSlot role={now.role} size="md" nameplate status="working" />
      <span className="au-live-text">
        <b className="au-shine">{now.verb}</b>
        {now.text && <span>{now.text}</span>}
      </span>
      <span className="au-live-time">
        Working for <Elapsed id={clockId} live />
      </span>
    </div>
  );
}

export interface RunGroupProps {
  group: RunGroup;
  clockId: string;
  live: boolean;
  open: boolean;
  proposals: ProposalView[];
  onToggle: (key: string) => void;
}

/** One run: a header that folds it, the live line while it works, its steps when open, and its waiting decisions. */
export const RunGroupView = memo(function RunGroupView({ group, clockId, live, open, proposals, onToggle }: RunGroupProps) {
  const own = proposalsOf(group, proposals);
  const waiting = own.filter((p) => p.state === "AWAIT_OPERATOR");
  // folded, a run still shows what it proposed: waiting for you, or on its way through applied to verified
  const kept = own.filter((p) => p.state !== "DENIED" && p.state !== "EXPIRED");
  const gate = gateOf(group);
  const status = group.run ? STATUS_WORD[group.run.status] : undefined;
  const cost = usdOf(group);
  const last = group.records[group.records.length - 1];
  const panel = `au-steps-${group.key.replace(/[^\w-]/g, "_")}`;
  return (
    <li className={`au-group${live ? " live" : ""}${open ? " open" : ""}${waiting.length ? " waiting" : ""}`} data-run={group.key}>
      <button type="button" className="au-head" aria-expanded={open} aria-controls={panel} onClick={() => onToggle(group.key)}>
        <svg className="au-chev" viewBox="0 0 16 16" aria-hidden="true">
          <path d="M6 4l4 4-4 4" />
        </svg>
        <Faces group={group} live={live} />
        <span className="au-title">
          <b>{GROUP_TITLE[group.kind]}</b>
          {group.runId && <span className="mono">{group.runId}</span>}
        </span>
        <span className="au-sum">{groupSummary(group, live)}</span>
        <span className="au-side">
          {gate && (
            <Pill tone={gate.admitted === gate.claimed ? "ok" : "watch"} title={`The AI claimed ${verdictWord(gate.claimed)}; the verdict gate admitted ${verdictWord(gate.admitted)}`}>
              {verdictWord(gate.admitted)}
            </Pill>
          )}
          {status && <Pill tone={status.tone}>{status.word}</Pill>}
          {waiting.length > 0 && <Pill tone="alarm">{waiting.length} waiting</Pill>}
          {cost > 0 && <span className="mono">{usd(cost)}</span>}
          {!live && <Elapsed id={clockId} live={false} className="mono" />}
          <span className="mono">{hhmm(last.sim_ts)}</span>
        </span>
      </button>
      {live && <LiveRow group={group} clockId={clockId} />}
      {open ? (
        <ol className="au-steps" id={panel}>
          {group.steps.map((s) => (
            <StepRow key={s.key} step={s} proposals={own} />
          ))}
        </ol>
      ) : (
        kept.length > 0 && (
          <ol className="au-steps" id={panel}>
            {kept.map((p) => (
              <ApprovalRow key={p.id} proposal={p} at={group.records.find((r) => r.action_id === p.id)?.sim_ts} />
            ))}
          </ol>
        )
      )}
    </li>
  );
});
