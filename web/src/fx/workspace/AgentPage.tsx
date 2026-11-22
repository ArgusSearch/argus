// Agent activity: every run of the Argus agent and every step of it, in the order it happened. What the model
// said before a check, the check and its prediction, what came back, what the verdict gate let through, what was
// proposed and decided. Numbers in these lines were rendered by the host from receipts, never typed by the model.

import { useMemo, useState } from "react";
import { AgentReceiptChips } from "../../components/Receipts";
import { roleOf, type ActivityKind, type ActivityRecord, type RunSummary } from "../../lib/agent";
import { AvatarSlot } from "./AvatarSlot";
import { dayLabel, hhmm, humanize } from "../../lib/format";
import { openIncidentPage } from "../nav";
import { useAgentDemo } from "../../lib/agentDemo";
import { useAgent } from "./agent";
import { VERDICT, type Tone } from "./plain";
import { Card, Pill } from "./ui";

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

const RUN_KIND: Record<RunSummary["kind"], string> = {
  investigate: "Investigation",
  ask: "Question",
  morning: "Morning report",
  verify_effect: "Effect check",
};

const STATUS: Record<RunSummary["status"], { word: string; tone: Tone }> = {
  running: { word: "running", tone: "probe" },
  done: { word: "done", tone: "ok" },
  budget: { word: "stopped at its budget", tone: "watch" },
  failed: { word: "failed", tone: "alarm" },
  fallback: { word: "handed to the fixed checklist", tone: "watch" },
};

/** the lines that name an incident with a link; the rest of a run is about the same incident */
const LINKED = new Set<ActivityKind>(["run_started", "report", "action_proposed", "effect_checked"]);

const verdictWord = (code: string) => VERDICT[code as keyof typeof VERDICT]?.label ?? humanize(code.toLowerCase());
const usd = (n: number) => `$${n < 0.1 ? n.toFixed(3) : n.toFixed(2)}`;

function Outcome({ outcome }: { outcome: string | null }) {
  if (!outcome) return null;
  const tone: Tone = /refut|ruled/i.test(outcome) ? "alarm" : /confirm|valid|consistent|held/i.test(outcome) ? "ok" : "muted";
  return <Pill tone={tone}>{humanize(outcome)}</Pill>;
}

function Line({ r }: { r: ActivityRecord }) {
  const k = KIND[r.kind];
  const o = r.observation;
  return (
    <li className={`ag-line a-${r.actor} k-${r.kind}`}>
      <span className="ag-time mono">{hhmm(r.sim_ts)}</span>
      <AvatarSlot role={roleOf(r)} size="md" nameplate status={r.kind === "rejected" || r.kind === "fallback" ? "alarm" : r.kind === "action_proposed" ? "waiting" : undefined} />
      <div className="ag-body">
        <span className="ag-kind">
          <span className={`ag-who ${r.actor}`} title={r.actor === "model" ? "the language model wrote this" : r.actor === "host" ? "Argus' own code ran this" : "a person did this"}>
            {r.actor === "model" ? "AI" : r.actor === "host" ? "Argus" : "You"}
          </span>
          <Pill tone={k.tone}>{k.word}</Pill>
          {r.tool && <span className="mono ag-tool">{r.tool}</span>}
          {r.kind === "tool_result" && <Outcome outcome={o?.outcome ?? null} />}
        </span>
        {r.text && <p className="ag-text">{r.text}</p>}
        {r.kind === "tool_call" && o && (o.hypothesis || o.prediction) && (
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
        {r.kind === "tool_result" && o && !r.text && <p className="ag-text">{o.summary}</p>}
        <span className="ag-meta">
          <AgentReceiptChips links={r.receipt_links.length ? r.receipt_links : (o?.receipt_refs ?? [])} />
          {r.model && (
            <span className="mono">
              {r.model} · {r.input_tokens ?? 0} in / {r.output_tokens ?? 0} out{r.usd !== null ? ` · ${usd(r.usd)}` : ""}
            </span>
          )}
          {r.incident_id && LINKED.has(r.kind) && (
            <button className="ag-link" onClick={() => openIncidentPage(r.incident_id as string)}>
              {r.incident_id}
            </button>
          )}
        </span>
      </div>
    </li>
  );
}

function RunCard({ run }: { run: RunSummary }) {
  const s = STATUS[run.status];
  return (
    <li className="ag-run">
      <span className="ag-run-head">
        <b>{RUN_KIND[run.kind]}</b>
        <span className="mono">{run.run_id}</span>
        <Pill tone={s.tone}>{s.word}</Pill>
      </span>
      <span className="ag-run-line">
        {dayLabel(run.sim_ts)} {hhmm(run.sim_ts)} · {run.llm_calls} model calls · {run.tool_calls} checks · {usd(run.usd)}
      </span>
      {run.gate && (
        <span className="ag-run-line">
          AI claimed <b>{verdictWord(run.gate.claimed)}</b>, the gate admitted <b>{verdictWord(run.gate.admitted)}</b>
          {run.gate.reasons.length ? ` (${run.gate.reasons.join("; ")})` : ""}
        </span>
      )}
      {run.fallback && <span className="ag-run-line ag-fallback">{run.fallback}</span>}
      {run.incident_id && (
        <button className="ag-link" onClick={() => openIncidentPage(run.incident_id as string)}>
          Open {run.incident_id}
        </button>
      )}
    </li>
  );
}

export function AgentPage() {
  const agent = useAgent();
  // the sealed presentation is a recorded model run, whatever mode the server's own agent is in
  const presenting = useAgentDemo() !== null;
  const [quiet, setQuiet] = useState(false);
  const lines = useMemo(() => agent.records.filter((r) => quiet || r.kind !== "watch"), [agent.records, quiet]);
  const spent = agent.runs.reduce((s, r) => s + r.usd, 0);
  const running = agent.runs.find((r) => r.status === "running");
  return (
    <main className="fx-dash ws-page ws-agent" aria-label="agent activity">
      <header className="ws-head">
        <span className="fx-hud ws-kicker">Agent activity{presenting ? " · recorded model run" : agent.health ? ` · ${agent.health.mode}` : ""}</span>
        <h1>{running ? `Argus is on it: ${RUN_KIND[running.kind].toLowerCase()} ${running.run_id}` : "What the Argus agent did on its own"}</h1>
        <p>
          Each step the agent took: what it said before a check, the check and its prediction, what came back, and what the verdict gate let through.
          Every number comes from a receipt; the model never types one.
        </p>
      </header>
      {!agent.enabled && (
        <p className="fx-empty">
          {agent.health?.reason ?? "The agent is off for this run (no agent routes on the API)"}. Argus investigated with its fixed checklist; the bench runs it too.
        </p>
      )}
      {agent.enabled && (
        <div className="ag-grid">
          <Card
            title="Steps"
            className="ag-steps"
            action={
              <label className="ag-toggle">
                <input type="checkbox" checked={quiet} onChange={(e) => setQuiet(e.target.checked)} /> show quiet hours
              </label>
            }
          >
            {lines.length === 0 ? <p className="fx-empty">Nothing yet: quiet hours need no model call.</p> : <ol className="ag-lines">{lines.map((r) => <Line key={r.seq} r={r} />)}</ol>}
          </Card>
          <Card title="Runs" className="ag-runs">
            <p className="ag-spent">
              {agent.runs.length} run{agent.runs.length === 1 ? "" : "s"} · {usd(spent)} spent on model calls
            </p>
            <ul className="ag-run-list">
              {[...agent.runs].reverse().map((r) => (
                <RunCard key={r.run_id} run={r} />
              ))}
            </ul>
          </Card>
        </div>
      )}
    </main>
  );
}
