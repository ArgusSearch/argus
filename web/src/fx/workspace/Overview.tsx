// The overview, the workspace's start page: five KPI tiles in plain words, the shop's health score with the
// four checks it is the average of, this week's decisions (proposed actions with their cost and an approve
// button), the key metrics in words, the 3D preview of an incident's path and the track record.

import { useEffect, useMemo, useRef, useState } from "react";
import { count, eur, dayLabel, hhmm } from "../../lib/format";
import { publicApi } from "../../lib/deployment";
import type { RunView } from "../../lib/store";
import type { Graph } from "../../lib/types";
import { useText } from "../../settings/language";
import { views as reads } from "../../views/data";
import { metricStatus } from "../../views/model";
import type { Scorecard } from "../../views/scorecard";
import { GraphStage, sceneAvailable } from "../GraphStage";
import { go, openIncidentPage } from "../nav";
import { ActionCard } from "./ActionCard";
import { proposalFor, useAgent, useHumanActions } from "./agent";
import { AgentTeam, AvatarSlot } from "./AvatarSlot";
import { activityAvatarRole } from "../../village/avatars/state";
import { health, keyMetrics, tasks, tiles, type Check, type Health, type Task, type Tile } from "./health";
import { CountUp, useCountUp, usePointerLight } from "./motion";
import { affectedPath, type PathSubject } from "./path";
import { metricName, STATE, unusualness, VERDICT, wherePhrase } from "./plain";
import { Card, Pill, Spark, Term, useIncidents } from "./ui";
import type { WorkspaceProps } from "./Workspace";

interface ConnectionStatus {
  id: string;
  status: string;
  target: string | null;
}

const connections = Object.values(import.meta.glob<{ listConnections: () => Promise<ConnectionStatus[]> }>(
  "../../settings/connections/api.ts",
)).at(0);

function headline(view: RunView, h: Health): string {
  const open = Object.values(view.incidents).filter((i) => i.state !== "resolved");
  if (open.length) return open.length === 1 ? "One incident needs your attention" : `${open.length} incidents need your attention`;
  if (!view.simTs) return "Waiting for the first hour of data";
  if (h.score !== null && h.score < 100) return "Running, with something to keep an eye on";
  return "All clear: nothing needs you right now";
}

export function Overview({ graph, view, onSelectNode }: WorkspaceProps) {
  const h = health(view, graph);
  const subject = affectedPath(view);
  const { incidents } = useIncidents(view);
  const agent = useAgent();
  const proposed = useMemo(() => new Set(agent.proposals.map((p) => p.incident_ref)), [agent.proposals]);
  const todo = useMemo(() => tasks(incidents, graph, proposed), [incidents, graph, proposed]);
  const page = useRef<HTMLElement>(null);
  const [selectedSource, setSelectedSource] = useState("");
  const [connected, setConnected] = useState<ConnectionStatus[] | null>(null);
  const tr = useText();
  usePointerLight(page);
  const humans = useHumanActions(view);
  const sources = new Map<string, string[]>();
  for (const node of graph?.nodes ?? []) {
    if (!node.source?.startsWith("connector:")) continue;
    const id = node.source.slice("connector:".length);
    if (connections && !connected?.some((connection) => connection.id === id && connection.status === "connected")) continue;
    const metrics = sources.get(id) ?? [];
    metrics.push(node.id);
    sources.set(id, metrics);
  }
  useEffect(() => {
    if (publicApi || !connections || !graph?.nodes.some((node) => node.source?.startsWith("connector:"))) return;
    let current = true;
    void connections().then((api) => api.listConnections()).then(
      (list) => { if (current) setConnected(list); },
      () => { if (current) setConnected([]); },
    );
    return () => { current = false; };
  }, [graph]);
  const sourceMetrics = sources.get(selectedSource);
  const limits = agent.health?.public_limits;
  const stored = limits?.stored_investigation;
  return (
    <main ref={page} className="fx-dash ws-page ws-overview" aria-label="overview">
      <header className="ws-head">
        <span className="fx-hud ws-kicker">Overview{view.simTs ? ` · ${dayLabel(view.simTs)} ${hhmm(view.simTs)}` : ""}</span>
        <div>
          {sources.size > 0 ? <select className="btn" aria-label={tr("Dashboard source")}
            value={sourceMetrics ? selectedSource : ""} onChange={(event) => setSelectedSource(event.target.value)}>
            <option value="">{tr("Example shop")}</option>
            {[...sources.keys()].sort().map((id) => {
              const name = id.charAt(0).toUpperCase() + id.slice(1);
              const target = connected?.find((connection) => connection.id === id)?.target;
              return <option key={id} value={id}>{target ? `${name} · ${target}` : name}</option>;
            })}
          </select> : <p>{tr("Example shop")}</p>}
        </div>
        {!sourceMetrics && <>
        <h1>{headline(view, h)}</h1>
        <p>Argus checks the shop's key numbers every hour, investigates anomalies, and asks for approval before acting.</p>
        {limits?.daily_usd !== undefined && <p className="fx-card-note">
          {limits.session_hour} live investigations per session per hour · {limits.ip_hour} per IP per hour · ${limits.spent_today_usd?.toFixed(2)} of ${limits.daily_usd.toFixed(2)} today (UTC)
        </p>}
        {limits?.message && <p className="fx-card-note" role="status">{limits.message}</p>}
        </>}
      </header>
      {sourceMetrics ? <MetricsCard graph={graph} view={view} onSelectNode={onSelectNode} ids={sourceMetrics} /> : <>
      {stored && <Card light title={`Stored investigation from ${new Date(stored.stored_at).toLocaleDateString(undefined, { timeZone: "UTC", dateStyle: "medium" })}`}>
        <p>{stored.title}</p>
        {stored.report && <details>
          <summary>Read investigation</summary>
          <pre style={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>{stored.report}</pre>
        </details>}
      </Card>}
      <section className="ws-tiles" aria-label="key figures">
        {tiles(view, graph, humans).map((t) => (
          <TileCard key={t.key} tile={t} />
        ))}
      </section>
      {view.scoredSeries > 0 && (
        <dl className="ws-compression" aria-label="From metric checks to incidents this run">
          <div><dt>Metric checks</dt><dd>{count(view.scoredSeries)}</dd></div>
          <div><dt>Signals flagged</dt><dd>{count(view.anomalies.length)}</dd></div>
          <div><dt>Incidents filed</dt><dd>{count(Object.keys(view.incidents).length)}</dd></div>
        </dl>
      )}
      <div className="ws-grid">
        <div className="ws-col">
          <HealthCard h={h} />
          {graph && subject && sceneAvailable() && <PathCard graph={graph} view={view} subject={subject} onSelectNode={onSelectNode} />}
          <MetricsCard graph={graph} view={view} onSelectNode={onSelectNode} />
        </div>
        <div className="ws-col">
          <TasksCard todo={todo} view={view} />
          {agent.enabled && <AgentCard />}
          <TrackRecordCard />
        </div>
      </div>
      </>}
    </main>
  );
}

function TileCard({ tile }: { tile: Tile }) {
  return (
    <div className={`ws-tile t-${tile.tone}`} title={tile.hint} data-light="">
      <span className="ws-tile-label">{tile.term ? <Term term={tile.term}>{tile.label}</Term> : tile.label}</span>
      <span className="ws-tile-value">
        <b aria-label={tile.value}>
          <CountUp value={tile.amount} format={tile.money ? (n) => eur(Math.round(n)) : undefined} />
        </b>
        {tile.unit && <span>{tile.unit}</span>}
      </span>
      <span className="ws-tile-change">{tile.change}</span>
      {tile.series.length > 1 ? <Spark values={tile.series} /> : <span className="ws-tile-spacer" aria-hidden="true" />}
    </div>
  );
}

/* ------------------------------------------------------------------ health */

/** The gauge: a 240° arc from the lower left to the lower right, filled to the score. */
function Gauge({ score: target, tone }: { score: number | null; tone: Health["tone"] }) {
  const counted = useCountUp(target ?? 0, 1400);
  const score = target === null ? null : Math.round(counted);
  const r = 78;
  const c = { x: 100, y: 100 };
  const start = 150; // degrees, measured clockwise from the positive x axis
  const sweep = 240;
  const point = (deg: number) => {
    const rad = (deg * Math.PI) / 180;
    return `${(c.x + r * Math.cos(rad)).toFixed(2)},${(c.y + r * Math.sin(rad)).toFixed(2)}`;
  };
  const arc = (from: number, to: number) => `M${point(from)} A${r},${r} 0 ${to - from > 180 ? 1 : 0} 1 ${point(to)}`;
  const value = target === null ? 0 : Math.max(0, Math.min(100, counted));
  const end = start + (sweep * value) / 100;
  return (
    <svg className={`ws-gauge t-${tone}`} viewBox="0 0 200 172" role="img" aria-label={target === null ? "Shop health not scored yet" : `Shop health ${target} of 100`}>
      <defs>
        <linearGradient id="ws-gauge-ice" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="var(--ws-gauge-from)" />
          <stop offset="1" stopColor="var(--ws-gauge-to)" />
        </linearGradient>
      </defs>
      <path className="ws-gauge-track" d={arc(start, start + sweep)} />
      {value > 0 && <path className="ws-gauge-value" d={arc(start, Math.max(end, start + 0.5))} />}
      {Array.from({ length: 11 }, (_, i) => {
        const deg = start + (sweep * i) / 10;
        const rad = (deg * Math.PI) / 180;
        const inner = r - 14;
        return (
          <line
            key={i}
            className="ws-gauge-tick"
            x1={c.x + inner * Math.cos(rad)}
            y1={c.y + inner * Math.sin(rad)}
            x2={c.x + (inner - (i % 5 === 0 ? 6 : 3)) * Math.cos(rad)}
            y2={c.y + (inner - (i % 5 === 0 ? 6 : 3)) * Math.sin(rad)}
          />
        );
      })}
      <text className="ws-gauge-score" x={c.x} y={c.y + 8} textAnchor="middle">
        {score === null ? "–" : score}
      </text>
      <text className="ws-gauge-of" x={c.x} y={c.y + 30} textAnchor="middle">
        of 100
      </text>
    </svg>
  );
}

function CheckBar({ c }: { c: Check }) {
  return (
    <li className={`ws-check t-${c.tone}`}>
      <span className="ws-check-bar" aria-hidden="true">
        <i style={{ height: `${Math.round(100 * c.share)}%` }} />
      </span>
      <b>
        <CountUp value={Math.round(100 * c.share)} ms={1200} />%
      </b>
      <span className="ws-check-label">{c.label}</span>
      <span className="ws-check-detail">{c.detail}</span>
    </li>
  );
}

function HealthCard({ h }: { h: Health }) {
  const weakest = [...h.checks].sort((a, b) => a.share - b.share)[0];
  return (
    <Card title="Shop health" term="Health score" className="ws-health" light>
      <div className="ws-health-body">
        <div className="ws-health-gauge">
          <Gauge score={h.score} tone={h.tone} />
          <p>
            {h.score === null
              ? "Scored from the first hour of data."
              : h.score >= 100
                ? "Every check passes."
                : `Held back by: ${weakest.label.toLowerCase()} (${weakest.detail}).`}
          </p>
        </div>
        <ul className="ws-checks" aria-label="the four checks">
          {h.checks.map((c) => (
            <CheckBar key={c.key} c={c} />
          ))}
        </ul>
      </div>
      <p className="fx-card-note">The score is the plain average of the four checks: no weights, no model.</p>
    </Card>
  );
}

/* ------------------------------------------------------------------ tasks */

function TaskItem({ task, view }: { task: Task; view: RunView }) {
  const state = STATE[task.state];
  const done = task.state === "resolved";
  return (
    <li className={`ws-task${done ? " done" : ""}`} data-light="">
      <div className="ws-task-head">
        <span className="mono">{task.id}</span>
        <Pill tone={state.tone} title={state.help}>
          {state.label}
        </Pill>
        <Pill tone={VERDICT[task.verdict].tone} title={VERDICT[task.verdict].help}>
          {VERDICT[task.verdict].label}
        </Pill>
        <span className="ws-task-eur" title="cost so far">
          <CountUp value={task.eur} format={(n) => eur(Math.round(n))} />
        </span>
      </div>
      <p className="ws-task-title">{task.headline}</p>
      <ActionCard
        incidentId={task.id}
        incidentState={task.state}
        fallback={task.action ? { text: task.action, needsApproval: task.needsApproval } : null}
        view={view}
        compact
      />
      <div className="ws-task-foot">
        <button className="btn" onClick={() => openIncidentPage(task.id)}>
          See why
        </button>
      </div>
    </li>
  );
}

function TasksCard({ todo, view }: { todo: Task[]; view: RunView }) {
  const agent = useAgent();
  // waiting = a proposal that awaits a decision, or (without the agent) an open incident with an action
  const open = todo.filter((t) => {
    const p = agent.enabled ? proposalFor(agent, t.id) : null;
    return p ? p.state === "AWAIT_OPERATOR" : t.state !== "resolved";
  }).length;
  return (
    <Card
      title="This week: your decisions"
      className="ws-tasks"
      light
      action={
        <button className="btn" onClick={() => go("incidents")}>
          All incidents
        </button>
      }
    >
      {todo.length === 0 ? (
        <p className="fx-empty">Nothing to decide. Argus proposes an action here when an incident needs one, with its cost.</p>
      ) : (
        <>
          <p className="ws-tasks-sum">
            {open ? `${open} waiting for you` : "Nothing waiting"} · {eur(todo.reduce((s, t) => s + t.eur, 0))} at stake this week
          </p>
          <ul className="ws-task-list">
            {todo.map((t) => (
              <TaskItem key={t.id} task={t} view={view} />
            ))}
          </ul>
        </>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ agent */

/** The agent at a glance: what it is doing now, its last steps, and the way to the full activity. */
function AgentCard() {
  const agent = useAgent();
  const running = agent.runs.find((r) => r.status === "running");
  const lines = agent.records.filter((r) => r.kind !== "watch").slice(-4);
  return (
    <Card
      title="Argus agent"
      className="ws-agent-card"
      light
      action={
        <button className="btn" onClick={() => go("agent")}>
          All activity
        </button>
      }
    >
      <p className="ws-agent-now">
        <i className={running ? "on" : undefined} aria-hidden="true" />
        {running ? `Working: ${running.kind === "ask" ? "answering a question" : running.kind === "verify_effect" ? "checking an action's effect" : "investigating"}` : "Watching. Quiet hours need no model call."}
      </p>
      <AgentTeam />
      {lines.length > 0 && (
        <ol className="ws-agent-lines">
          {lines.map((r) => {
            const role = activityAvatarRole(r);
            const current = agent.avatars[role];
            const cue = current?.key === r.seq ? current : undefined;
            return (
              <li key={r.seq}>
                <AvatarSlot role={role} cue={cue} paused={!cue} />
                <span className="mono">{hhmm(r.sim_ts)}</span>
                <span>{r.text || r.observation?.summary || r.kind.replace(/_/g, " ")}</span>
              </li>
            );
          })}
        </ol>
      )}
    </Card>
  );
}

/* ------------------------------------------------------------------ key metrics */

function MetricsCard({ graph, view, onSelectNode, ids = keyMetrics(graph) }: { graph: Graph | null; view: RunView; onSelectNode: (id: string) => void; ids?: string[] }) {
  const { wiggle_z: wiggle, alarm_z: alarm } = view.thresholds;
  return (
    <Card title="Key metrics, this hour" term="|z|" className="ws-metrics" light>
      <ul className="ws-metric-list">
        {ids.map((id) => {
          const status = metricStatus(view, id);
          const words = unusualness(status.z, wiggle, alarm);
          const special = status.state === "root" ? "root of the incident" : status.state === "symptom" ? "knock-on effect" : status.state === "checking" ? "being checked" : null;
          const tone = status.state === "root" ? "alarm" : status.state === "checking" ? "probe" : words.tone;
          const fill = status.z === null ? 0 : Math.min(status.z / (alarm * 1.25), 1);
          return (
            <li key={id}>
              <button className={`ws-metric t-${tone}`} onClick={() => onSelectNode(id)} title={`${metricName(graph, id)}: how unusual ${status.z === null ? "–" : status.z.toFixed(1)} (alarm at ${alarm})`}>
                <span className="ws-metric-name">{metricName(graph, id)}</span>
                <span className="ws-metric-word">{special ?? words.word}</span>
                <span className="ws-metric-meter" aria-hidden="true">
                  <i style={{ width: `${(100 * fill).toFixed(1)}%` }} />
                  <em style={{ left: `${(100 / 1.25).toFixed(1)}%` }} />
                </span>
                <Spark values={(view.zHistory[id] ?? []).slice(-36)} className="ws-metric-spark" />
              </button>
            </li>
          );
        })}
      </ul>
      <p className="fx-card-note">
        Each bar shows how far the hour is from the same hour of the last four weeks; the mark is the alarm threshold. Click a metric for its details.
      </p>
    </Card>
  );
}

/* ------------------------------------------------------------------ 3D preview */

function PathCard({ graph, view, subject, onSelectNode }: { graph: Graph; view: RunView; subject: PathSubject; onSelectNode: (id: string) => void }) {
  const inc = subject.incident;
  const word = inc ? STATE[inc.state].label : subject.phase === "anomaly" ? "Detected" : "Being checked";
  return (
    <Card
      title="Where it hits"
      className="fx-card-path"
      action={
        <span className="fx-card-actions">
          <Pill tone={inc ? STATE[inc.state].tone : "probe"}>{word}</Pill>
          <button className="btn" onClick={() => go("graph")}>
            Open visualization
          </button>
        </span>
      }
    >
      <div className="fx-path-scene">
        <GraphStage graph={graph} view={view} onSelectNode={onSelectNode} variant="preview" />
      </div>
      <p className="fx-card-note">
        {metricName(graph, subject.node)}
        {inc ? ` for ${wherePhrase(inc.segment)}` : ""}, and every metric it pulls down with it. Click a block to open it.
      </p>
    </Card>
  );
}

/* ------------------------------------------------------------------ track record */

const REFERENCE: Record<string, string> = {
  "argus-stage1": "Argus Stage 1 alone (fixed checklist)",
  threshold: "Plain threshold alarm",
};

function TrackRecordCard() {
  const [card, setCard] = useState<Scorecard | null>();
  const [failed, setFailed] = useState(false);
  useEffect(() => {
    let live = true;
    reads.benchResults().then(
      (s) => live && setCard(s),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, []);
  const argus = card?.summaries.find((s) => s.agent === "argus");
  const right = (s: { pass_at_1: number | null; runs: number }) => Math.round((s.pass_at_1 ?? 0) * s.runs);
  return (
    <Card
      title="Track record"
      term="pass@1"
      className="ws-record"
      light
      action={
        <button className="btn" onClick={() => go("scorecard")}>
          Details
        </button>
      }
    >
      {!argus && <p className="fx-empty">{failed ? "The track record could not be loaded." :
        card === undefined ? "Loading the track record…" :
          card === null ? "The server has no benchmark results yet." : "This benchmark did not include Argus."}</p>}
      {argus && card && (
        <>
          <div className="ws-record-hero">
            <div>
              <b aria-label={`${right(argus)} of ${argus.runs}`}>
                <CountUp value={right(argus)} ms={1100} />/{argus.runs}
              </b>
              <span>test runs right</span>
            </div>
            <div>
              <b>
                <CountUp value={argus.false_alarms} />
              </b>
              <span>false alarms</span>
            </div>
          </div>
          <p className="ws-record-what">
            {card.scenarios.length} scenarios, {card.seeds.length} worlds each. The answers were locked away before Argus ran.
          </p>
          <span className="ws-record-cap">For comparison, on the same worlds</span>
          <ul className="ws-record-refs" aria-label="for comparison">
            {card.summaries
              .filter((s) => s.agent !== "argus")
              .map((s) => (
                <li key={s.agent}>
                  <span>{REFERENCE[s.agent] ?? s.agent}</span>
                  <b>
                    {right(s)}/{s.runs} right
                  </b>
                  <b>{s.false_alarms} false alarms</b>
                </li>
              ))}
          </ul>
          <p className="fx-card-note">
            Latest bench run · {dayLabel(card.created_at)} {hhmm(card.created_at)} · {argus.runs} Argus runs
          </p>
        </>
      )}
    </Card>
  );
}
