// Agent activity: every run of the Argus agent, each folded to one line once it is done, the running one open with
// what it is doing now. Open a run for its steps: what the model said before a check, the check and its prediction,
// what came back, what the verdict gate let through, what was proposed and decided. A proposal waiting for you stays
// in view with its approve and deny. Numbers in these lines were rendered by the host from receipts, never typed by
// the model.

import { useCallback, useLayoutEffect, useMemo, useState } from "react";
import { groupRuns, isLive } from "../../agent-ui/activity";
import { runClock } from "../../agent-ui/clock";
import { JumpToLatest, useFollowTail } from "../../agent-ui/hooks";
import { RunGroupView, usd } from "../../agent-ui/RunLog";
import { DEFAULT_QUERY } from "../../analysis/shell/query";
import { analysisHref, followLink, navigateWorkspaceURL } from "../../analysis/shell/location";
import { type RunSummary } from "../../lib/agent";
import { dayLabel, hhmm, humanize } from "../../lib/format";
import { openIncidentPage } from "../nav";
import { useAgentDemo } from "../../lib/agentDemo";
import { useAgent, type AgentState } from "./agent";
import { VERDICT, type Tone } from "./plain";
import { Card, Pill } from "./ui";

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

const verdictWord = (code: string) => VERDICT[code as keyof typeof VERDICT]?.label ?? humanize(code.toLowerCase());

function RunCard({ run, onShow }: { run: RunSummary; onShow: (key: string) => void }) {
  const s = STATUS[run.status];
  const liveFixHref = analysisHref({ ...DEFAULT_QUERY, page: "live-fix", runId: run.run_id });
  return (
    <li className="ag-run">
      <span className="ag-run-head">
        <b>{RUN_KIND[run.kind]}</b>
        <button className="ag-link mono" title="Show this run's steps" onClick={() => onShow(run.run_id)}>
          {run.run_id}
        </button>
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
      <a className="ag-link" href={liveFixHref} onClick={(event) => followLink(event, () => navigateWorkspaceURL(liveFixHref))}>Open Live Fix</a>
    </li>
  );
}

export function AgentPage() {
  const agent = useAgent();
  return <AgentActivity key={agent.scope} agent={agent} />;
}

function AgentActivity({ agent }: { agent: AgentState }) {
  // the sealed presentation is a recorded model run, whatever mode the server's own agent is in
  const presenting = useAgentDemo() !== null;
  const [quiet, setQuiet] = useState(false);
  // Explicit choices take precedence over the default, which expands live runs.
  const [folds, setFolds] = useState<ReadonlyMap<string, boolean>>(new Map());
  const records = useMemo(() => agent.records.filter((r) => quiet || r.kind !== "watch"), [agent.records, quiet]);
  const groups = useMemo(() => groupRuns(records, agent.runs), [records, agent.runs]);
  const live = useMemo(() => new Set(groups.filter((g) => isLive(g, presenting)).map((g) => g.key)), [groups, presenting]);
  const tail = useFollowTail(records.length);
  const spent = agent.runs.reduce((s, r) => s + r.usd, 0);
  const running = agent.runs.find((r) => r.status === "running");
  const waiting = agent.waiting;
  const newest = groups[groups.length - 1]?.key;

  // every run is timed from when this page first saw it live, open or folded
  useLayoutEffect(() => {
    const now = Date.now();
    for (const g of groups) runClock.observe(`${agent.scope}:${g.key}`, live.has(g.key), now);
  }, [agent.scope, groups, live]);

  const isOpen = (key: string) => folds.get(key) ?? live.has(key);
  const { release } = tail;
  const toggle = useCallback(
    (key: string) => {
      // opening a run above the newest is reading history: stop following the end
      if (key !== newest) release();
      setFolds((f) => new Map(f).set(key, !(f.get(key) ?? live.has(key))));
    },
    [newest, live, release],
  );
  const show = (key: string) => {
    release();
    setFolds((f) => new Map(f).set(key, true));
    requestAnimationFrame(() => document.querySelector(`.au-group[data-run="${CSS.escape(key)}"]`)?.scrollIntoView({ block: "start", behavior: "smooth" }));
  };

  return (
    <main className="fx-dash ws-page ws-agent" aria-label="agent activity">
      <header className="ws-head">
        <span className="fx-hud ws-kicker">Agent activity{presenting ? " · recorded model run" : agent.health ? ` · ${agent.health.mode}` : ""}</span>
        <h1>{running ? `Argus is on it: ${RUN_KIND[running.kind].toLowerCase()} ${running.run_id}` : "What the Argus agent did on its own"}</h1>
        <p>
          Each run folds to one line once it is done; open it for every step: what the AI said before a check, the check and its prediction, what came back,
          and what the verdict gate let through. Every number comes from a receipt; the model never types one.
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
            title={waiting ? `Runs · ${waiting} waiting for you` : "Runs"}
            className="ag-steps au-card"
            action={
              <label className="ag-toggle">
                <input type="checkbox" checked={quiet} onChange={(e) => setQuiet(e.target.checked)} /> show quiet hours
              </label>
            }
          >
            <div className="au-scroll" ref={tail.ref} tabIndex={0} role="region" aria-label="agent runs">
              {groups.length === 0 ? (
                <p className="fx-empty">Nothing yet: quiet hours need no model call.</p>
              ) : (
                <ol className="au-groups">
                  {groups.map((g) => (
                    <RunGroupView key={g.key} clockId={`${agent.scope}:${g.key}`} group={g} live={live.has(g.key)} open={isOpen(g.key)} proposals={agent.proposals} onToggle={toggle} />
                  ))}
                </ol>
              )}
            </div>
            <JumpToLatest tail={tail} noun="new" />
          </Card>
          <Card title="Run totals" className="ag-runs">
            <p className="ag-spent">
              {agent.runs.length} run{agent.runs.length === 1 ? "" : "s"} · {usd(spent)} spent on model calls
            </p>
            <ul className="ag-run-list">
              {[...agent.runs].reverse().map((r) => (
                <RunCard key={r.run_id} run={r} onShow={show} />
              ))}
            </ul>
          </Card>
        </div>
      )}
    </main>
  );
}
