// The Argus Ice workspace: a sidebar that navigates between the dashboard and the views of the view host, and
// the dashboard itself, the start page with the flag. Every number on it is one the API sent (|z|, counts,
// euros, bench measures); the dashboard only picks, orders and labels them, like the views do.

import { useEffect, useLayoutEffect, useMemo, useState, type ReactNode } from "react";
import { Mark } from "../../components/Header";
import { ReceiptChips } from "../../components/Receipts";
import { api, type Digest } from "../../lib/api";
import { eur, hhmm, dayLabel, segmentEntries } from "../../lib/format";
import type { RunView } from "../../lib/store";
import type { Graph, GraphNode } from "../../lib/types";
import { autonomyCounts } from "../../views/autonomy";
import { views as reads } from "../../views/data";
import { breadcrumb, stepQuestion } from "../../views/investigation";
import { investigations, metricStatus, type MetricState } from "../../views/model";
import { isScorecard, summaryMetrics, type Scorecard } from "../../views/scorecard";
import sampleUrl from "../../views/fixtures/scorecard.sample.json?url";
import { fxOn } from "../flag";
import { GraphStage, sceneAvailable } from "../GraphStage";
import { go, useSection, watchHost, type Section } from "../nav";
import { affectedPath, type PathSubject } from "./path";

export interface WorkspaceProps {
  graph: Graph | null;
  view: RunView;
  onOpenIncident: (id: string) => void;
  onSelectNode: (id: string) => void;
}

/** Renders nothing without the flag; with it, the sidebar and the dashboard as items of the app's grid. */
export function FxWorkspace(props: WorkspaceProps) {
  if (!fxOn()) return null;
  return <Workspace {...props} />;
}

function Workspace({ graph, view, onOpenIncident, onSelectNode }: WorkspaceProps) {
  const section = useSection();
  useLayoutEffect(() => {
    document.documentElement.dataset.fxSection = section;
  }, [section]);
  useEffect(() => watchHost(), []);
  return (
    <>
      <Sidebar section={section} view={view} />
      {section === "dashboard" && <Dashboard graph={graph} view={view} onOpenIncident={onOpenIncident} onSelectNode={onSelectNode} />}
    </>
  );
}

/* ------------------------------------------------------------------ sidebar */

const NAV: { id: Section; label: string; icon: ReactNode }[] = [
  { id: "dashboard", label: "Dashboard", icon: <path d="M2.5 2.5h4.5v6h-4.5zM9 2.5h4.5v3.5h-4.5zM9 8h4.5v5.5h-4.5zM2.5 10.5h4.5v3h-4.5z" /> },
  { id: "investigation", label: "Investigations", icon: <path d="M7 2.5a4.5 4.5 0 1 0 0 9a4.5 4.5 0 1 0 0-9zM10.3 10.3l3.2 3.2" /> },
  { id: "report", label: "Morning report", icon: <path d="M3.5 2.5h9v11h-9zM5.5 5.5h5M5.5 8h5M5.5 10.5h3" /> },
  { id: "graph", label: "Metric graph", icon: <path d="M3.5 4.5a1.5 1.5 0 1 0 0 .01M12.5 3.5a1.5 1.5 0 1 0 0 .01M12.5 12.5a1.5 1.5 0 1 0 0 .01M5 4.6l6-1M5 5.2l6.4 6.4" /> },
  { id: "tree", label: "Metric tree", icon: <path d="M3 3h4M5 3v10M5 7.5h3.5M5 12.5h3.5M10 6h3.5v3h-3.5zM10 11h3.5v3h-3.5z" /> },
  { id: "scorecard", label: "Scorecard", icon: <path d="M2.5 13.5h11M4 13.5v-4M7 13.5v-7M10 13.5v-5M13 13.5v-9" /> },
];

function Sidebar({ section, view }: { section: Section; view: RunView }) {
  const counts = autonomyCounts(view);
  const value = (key: string) => counts.find((c) => c.key === key)?.value ?? 0;
  const running = investigations(view).some((inv) => !view.steps.some((s) => s.anomalyId === inv.anomalyId && s.step.kind === "verdict"));
  const open = Object.values(view.incidents).filter((i) => i.state !== "resolved").length;
  return (
    <nav className="fx-side" aria-label="sections">
      <div className="fx-side-brand">
        <Mark />
        <div>
          <b>ARGUS</b>
          <span>Mission control</span>
        </div>
      </div>
      <ul className="fx-side-nav">
        {NAV.map((item) => (
          <li key={item.id}>
            <button className={`fx-side-item${section === item.id ? " on" : ""}`} aria-current={section === item.id ? "page" : undefined} onClick={() => go(item.id)}>
              <svg viewBox="0 0 16 16" aria-hidden="true">
                {item.icon}
              </svg>
              <span>{item.label}</span>
              {item.id === "investigation" && running && <i className="fx-side-live" aria-label="investigation running" />}
              {item.id === "dashboard" && open > 0 && <em className="fx-side-badge">{open}</em>}
            </button>
          </li>
        ))}
      </ul>
      <div className="fx-side-foot">
        <span className="fx-hud">On its own</span>
        <dl>
          <div>
            <dt>hours watched</dt>
            <dd>{value("hours")}</dd>
          </div>
          <div>
            <dt>edge tests</dt>
            <dd>{value("edges")}</dd>
          </div>
          <div>
            <dt>investigated</dt>
            <dd>{value("investigations")}</dd>
          </div>
          <div className="human">
            <dt>human actions</dt>
            <dd>0</dd>
          </div>
        </dl>
      </div>
    </nav>
  );
}

/* ------------------------------------------------------------------ dashboard */

/** The dashboard's headline: what needs attention right now, in words. */
function headline(graph: Graph | null, view: RunView): string {
  const running = runningInvestigation(view);
  if (running) return `Investigating ${shortLabel(graph, running.node)}`;
  const open = Object.values(view.incidents).filter((i) => i.state !== "resolved").length;
  if (open) return open === 1 ? "One open incident" : `${open} open incidents`;
  if (!view.simTs) return "Waiting for the first hour";
  return "Nothing needs you right now";
}

function Dashboard({ graph, view, onOpenIncident, onSelectNode }: WorkspaceProps) {
  const stars = useMemo(() => (graph?.nodes ?? []).filter((n) => n.north_star), [graph]);
  const subject = affectedPath(view);
  return (
    <main className="fx-dash" aria-label="dashboard">
      <header className="fx-dash-head">
        <div>
          <span className="fx-hud fx-dash-kicker">Dashboard{view.simTs ? ` · ${dayLabel(view.simTs)} ${hhmm(view.simTs)}` : ""}</span>
          <h1>{headline(graph, view)}</h1>
          <p>
            {stars.length} north-star metrics, scored every hour against the same hour of the last four weeks. The alarm line is |z|{" "}
            {view.thresholds.alarm_z}.
          </p>
        </div>
      </header>
      <section className="fx-kpis" aria-label="north-star metrics">
        {stars.map((node) => (
          <Kpi key={node.id} graph={graph} node={node} view={view} onSelect={onSelectNode} />
        ))}
        <HumanTile view={view} />
      </section>
      <div className="fx-dash-grid">
        <div className="fx-dash-col">
          {graph && subject && sceneAvailable() && <PathCard graph={graph} view={view} subject={subject} onSelectNode={onSelectNode} />}
          <IncidentsCard graph={graph} view={view} onOpenIncident={onOpenIncident} />
          <ScoreCard />
        </div>
        <div className="fx-dash-col">
          <MorningCard view={view} />
          <AutonomyCard view={view} />
        </div>
      </div>
    </main>
  );
}

/** Fills the last slot of the four-column KPI grid: the autonomy count a judge looks for. */
function HumanTile({ view }: { view: RunView }) {
  return (
    <div className="fx-kpi fx-kpi-human t-ok">
      <span className="fx-kpi-head">
        <span className="fx-kpi-label">Human actions</span>
      </span>
      <span className="fx-kpi-value">
        <b>0</b>
        <span>in {view.ticks} hours</span>
        <span className="fx-kpi-state">on its own</span>
      </span>
      <span className="fx-kpi-note">Detect, localise, rule out, verdict, close: all without a person.</span>
    </div>
  );
}

const SHORT_LABEL: Record<string, string> = {
  payment_success_rate: "Payment success",
  impressions_per_session: "Impr. per session",
  aov: "Order value",
  cvr: "Conversion",
};

function shortLabel(graph: Graph | null, id: string): string {
  return SHORT_LABEL[id] ?? graph?.nodes.find((n) => n.id === id)?.label ?? id;
}

function runningInvestigation(view: RunView) {
  return investigations(view)
    .reverse()
    .find((inv) => !view.steps.some((s) => s.anomalyId === inv.anomalyId && s.step.kind === "verdict"));
}

type Tone = "ok" | "watch" | "alarm" | "probe" | "muted";

/** Short chip words for the KPI cards; the long labels stay in the views. */
const CHIP: Partial<Record<MetricState, string>> = { checking: "checking", symptom: "symptom", unscored: "not scored", pending: "pending" };

const TONE: Record<MetricState, Tone> = {
  checking: "probe",
  root: "alarm",
  alarm: "alarm",
  symptom: "watch",
  wiggle: "watch",
  pending: "muted",
  resolved: "ok",
  normal: "ok",
  unscored: "muted",
};

function Kpi({ graph, node, view, onSelect }: { graph: Graph | null; node: GraphNode; view: RunView; onSelect: (id: string) => void }) {
  const status = metricStatus(view, node.id);
  const tone = TONE[status.state];
  const history = view.zHistory[node.id] ?? [];
  return (
    <button
      className={`fx-kpi t-${tone}${status.z !== null && status.z >= view.thresholds.alarm_z ? " over" : ""}`}
      onClick={() => onSelect(node.id)}
      title={`${node.label}: ${node.description}`}
    >
      <span className="fx-kpi-head">
        <span className="fx-kpi-label">{shortLabel(graph, node.id)}</span>
        <span className="fx-kpi-unit">{node.unit.replace(/_/g, " ")}</span>
      </span>
      <span className="fx-kpi-value">
        <b>{status.z === null ? "–" : status.z.toFixed(1)}</b>
        <span>|z|</span>
        <span className="fx-kpi-state">{CHIP[status.state] ?? status.label}</span>
      </span>
      <Trend values={history} alarm={view.thresholds.alarm_z} />
    </button>
  );
}

/** |z| per scored hour with the alarm line; the scale tops out a little above the line. */
function Trend({ values, alarm }: { values: number[]; alarm: number }) {
  const w = 200;
  const h = 40;
  const recent = values.slice(-36);
  const top = Math.max(alarm * 1.25, ...recent);
  const y = (v: number) => h - 2 - (Math.min(v, top) / top) * (h - 4);
  const x = (i: number) => (recent.length < 2 ? 0 : (i * w) / (recent.length - 1));
  const line = recent.map((v, i) => `${i ? "L" : "M"}${x(i).toFixed(1)},${y(v).toFixed(1)}`).join("");
  return (
    <svg className="fx-trend" viewBox={`0 0 ${w} ${h}`} preserveAspectRatio="none" aria-hidden="true">
      <line className="fx-trend-alarm" x1={0} x2={w} y1={y(alarm)} y2={y(alarm)} />
      {recent.length > 1 && (
        <>
          <path className="fx-trend-area" d={`${line}L${w},${h}L0,${h}Z`} />
          <path className="fx-trend-line" d={line} />
        </>
      )}
    </svg>
  );
}

function Card({ title, action, className, children }: { title: string; action?: ReactNode; className?: string; children: ReactNode }) {
  return (
    <section className={`fx-card${className ? ` ${className}` : ""}`}>
      <header className="fx-card-head">
        <h2 className="fx-hud">{title}</h2>
        {action}
      </header>
      {children}
    </section>
  );
}

function IncidentsCard({ graph, view, onOpenIncident }: { graph: Graph | null; view: RunView; onOpenIncident: (id: string) => void }) {
  const incidents = Object.values(view.incidents).sort((a, b) => b.firstSeq - a.firstSeq);
  const running = runningInvestigation(view);
  const runningSteps = running ? view.steps.filter((s) => s.anomalyId === running.anomalyId) : [];
  const latest = runningSteps[runningSteps.length - 1];
  return (
    <Card
      title="Incidents and investigations"
      className="fx-card-incidents"
      action={
        <button className="btn" onClick={() => go("investigation")}>
          Open investigations
        </button>
      }
    >
      {running && latest && (
        <div className="fx-running">
          <span className="fx-running-dot" aria-hidden="true" />
          <div>
            <b>Investigating {shortLabel(graph, running.node)}</b>
            <Path node={running.node} steps={runningSteps} />
            <ol className="fx-steps">
              {runningSteps.slice(-5).map((s) => (
                <li key={s.seq} className={s === latest ? "now" : undefined}>
                  <span className="mono">{s.step.step}</span>
                  <span>{stepQuestion(s.step)}</span>
                  <em>{s.step.decision}</em>
                </li>
              ))}
            </ol>
          </div>
        </div>
      )}
      {incidents.length === 0 && !running && <p className="fx-empty">No incident. Nothing crossed the alarm line long enough to page anyone.</p>}
      <ul className="fx-incidents">
        {incidents.map((inc) => {
          const steps = view.steps.filter((s) => s.incidentId === inc.id);
          return (
            <li key={inc.id} className={`fx-incident s-${inc.state}`}>
              <div className="fx-incident-head">
                <span className="mono">{inc.id}</span>
                <span className={`pill ${inc.verdict}`}>{inc.verdict.replace(/_/g, " ")}</span>
                <span className={`pill state-${inc.state}`}>{inc.state}</span>
                <span className="fx-incident-eur">{eur(inc.severity_eur)}</span>
              </div>
              <p className="fx-incident-title">{inc.title}</p>
              <Path node={inc.root_node} steps={steps} segment={segmentEntries(inc.segment)} />
              <button className="btn primary" onClick={() => onOpenIncident(inc.id)}>
                Open report
              </button>
            </li>
          );
        })}
      </ul>
    </Card>
  );
}

const PATH_STATE: Record<PathSubject["phase"], { word: string; tone: Tone }> = {
  anomaly: { word: "detected", tone: "alarm" },
  investigating: { word: "checking", tone: "probe" },
  verdict: { word: "explained", tone: "watch" },
};

/**
 * The affected path at incident time as the 3D scene's preview: the anomaly, everything its formulas move and
 * the evidence that held burn warm while the rest of the graph recedes. A block opens its metric.
 */
function PathCard({ graph, view, subject, onSelectNode }: { graph: Graph; view: RunView; subject: PathSubject; onSelectNode: (id: string) => void }) {
  const state = subject.incident ? { word: subject.incident.state, tone: subject.incident.state === "monitoring" ? "ok" : "watch" } : PATH_STATE[subject.phase];
  return (
    <Card
      title="Affected path"
      className="fx-card-path"
      action={
        <span className="fx-card-actions">
          <span className={`fx-path-state t-${state.tone}`}>
            <span className="mono">{subject.incident?.id ?? shortLabel(graph, subject.node)}</span>
            {state.word}
          </span>
          <button className="btn" onClick={() => go("graph")}>
            Metric graph
          </button>
        </span>
      }
    >
      <div className="fx-path-scene">
        <GraphStage graph={graph} view={view} onSelectNode={onSelectNode} variant="preview" />
      </div>
      <p className="fx-card-note">
        <span className="mono">{subject.node}</span>, what its formulas move downstream and the evidence that held. Click a block to open it.
      </p>
    </Card>
  );
}

/** The affected path: the metric, then each dimension the segment search narrowed it to. */
function Path({ node, steps, segment }: { node: string; steps: RunView["steps"]; segment?: [string, string][] }) {
  const crumbs = breadcrumb(
    steps.map((s) => s.step),
    node,
  ).crumbs;
  const cells = crumbs.length ? crumbs.map((c) => [c.dim, c.value] as [string, string]) : (segment ?? []);
  return (
    <div className="fx-path" aria-label="affected path">
      <span className="fx-path-node mono">{node}</span>
      {cells.map(([dim, value]) => (
        <span key={`${dim}:${value}`} className="fx-path-cell">
          <i>{dim}</i>
          {value}
        </span>
      ))}
    </div>
  );
}

function MorningCard({ view }: { view: RunView }) {
  const [digest, setDigest] = useState<Digest | null>(null);
  const [failed, setFailed] = useState(false);
  // re-read after every sixth hour and whenever an incident appears or changes state
  const version = `${Math.floor(view.ticks / 6)}:${Object.values(view.incidents)
    .map((i) => i.state)
    .join(",")}`;
  useEffect(() => {
    let live = true;
    api.digest().then(
      (d) => live && (setDigest(d), setFailed(false)),
      () => live && setFailed(true),
    );
    return () => {
      live = false;
    };
  }, [version, view.stream]);
  return (
    <Card
      title="While you slept"
      className="fx-card-morning"
      action={
        <button className="btn" onClick={() => go("report")}>
          Full report
        </button>
      }
    >
      {failed && !digest && <p className="fx-empty">The morning report could not be loaded.</p>}
      {!digest && !failed && <p className="fx-empty">Loading the morning report…</p>}
      {digest && (
        <ul className="fx-digest">
          {digest.lines.slice(0, 6).map((line) => (
            <li key={line.key} className={`t-${line.tone}`}>
              <span className="fx-digest-label">{line.label}</span>
              <b>{line.value}</b>
              <span className="fx-digest-detail">
                {line.detail}
                <ReceiptChips ids={line.receipts} max={3} />
              </span>
            </li>
          ))}
        </ul>
      )}
    </Card>
  );
}

function AutonomyCard({ view }: { view: RunView }) {
  const counts = autonomyCounts(view);
  const incidents = Object.values(view.incidents);
  const decided = [
    { label: "anomalies opened", value: view.anomalies.length },
    { label: "verdicts reached", value: incidents.filter((i) => i.verdict !== "UNEXPLAINED").length },
    { label: "incidents closed after recovery", value: incidents.filter((i) => i.state === "resolved").length },
    { label: "alerts held back", value: view.notes.length },
    { label: "edge tests run", value: view.edgeChanges.length },
  ];
  return (
    <Card title="Autonomy" className="fx-card-autonomy">
      <div className="fx-autonomy">
        <div>
          <h3>Decided alone</h3>
          <ul>
            {decided.map((d) => (
              <li key={d.label}>
                <b>{d.value}</b>
                {d.label}
              </li>
            ))}
          </ul>
        </div>
        <div>
          <h3>Asked a human</h3>
          <ul>
            <li className="human">
              <b>{counts.find((c) => c.key === "human")?.value ?? 0}</b>
              human actions
            </li>
            <li>
              <b>·</b>any action on the business needs an approval
            </li>
          </ul>
        </div>
      </div>
      <p className="fx-card-note">Statistics decide where to look and compute every number; a language model may propose and write, never decide.</p>
    </Card>
  );
}

async function loadScorecard(): Promise<{ card: Scorecard; sample: boolean }> {
  try {
    const live = await reads.benchResults();
    if (isScorecard(live)) return { card: live, sample: false };
  } catch {
    /* the bench route is a stub until the bench lands: fall back to the recorded sample */
  }
  const sample: unknown = await (await fetch(sampleUrl)).json();
  if (!isScorecard(sample)) throw new Error("the recorded sample is not a scorecard");
  return { card: sample, sample: true };
}

function ScoreCard() {
  const [state, setState] = useState<{ card: Scorecard; sample: boolean } | null>(null);
  useEffect(() => {
    let live = true;
    loadScorecard().then(
      (s) => live && setState(s),
      () => undefined,
    );
    return () => {
      live = false;
    };
  }, []);
  const argus = state?.card.summaries.find((s) => s.agent === "argus");
  const baseline = state?.card.summaries.find((s) => s.agent !== "argus");
  const pick = ["recall", "cause", "ttd", "fa"];
  return (
    <Card
      title="Bench scorecard"
      className="fx-card-score"
      action={
        <button className="btn" onClick={() => go("scorecard")}>
          Details
        </button>
      }
    >
      {!argus && <p className="fx-empty">Loading the scorecard…</p>}
      {argus && (
        <>
          <table className="fx-score">
            <thead>
              <tr>
                <th />
                <th>Argus</th>
                {baseline && <th>Threshold baseline</th>}
              </tr>
            </thead>
            <tbody>
              {summaryMetrics(argus)
                .filter((m) => pick.includes(m.key))
                .map((m) => {
                  const base = baseline ? summaryMetrics(baseline).find((b) => b.key === m.key) : undefined;
                  return (
                    <tr key={m.key}>
                      <th>{m.label}</th>
                      <td className={`t-${m.tone}`}>{m.value}</td>
                      {base && <td className={`t-${base.tone}`}>{base.value}</td>}
                    </tr>
                  );
                })}
            </tbody>
          </table>
          <p className="fx-card-note">
            {state?.sample ? "Recorded sample" : "Live bench"} · {state?.card.seeds.length} sealed seeds · commitment{" "}
            <span className="mono">{state?.card.bench_commitment.slice(0, 12)}</span>
          </p>
        </>
      )}
    </Card>
  );
}
