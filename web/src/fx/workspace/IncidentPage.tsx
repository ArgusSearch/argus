// One incident as a story, top to bottom: what happened, where, why, what it costs, what to do, and the evidence
// behind every number (the investigation's steps with their SQL receipts, folded away). Rendered from the
// findings the API serves; the internal terms stay in the evidence and in the glossary tooltips.

import { useEffect, useState } from "react";
import { TimeChart, type SeriesPoint } from "../../components/charts";
import { Num, ReceiptChips } from "../../components/Receipts";
import { api } from "../../lib/api";
import { dayLabel, eur, hhmm, humanize, pct, quantity } from "../../lib/format";
import { isRuledOut, type RunView } from "../../lib/store";
import type { Graph, Incident, IncidentState, Quantity, TrailStep } from "../../lib/types";
import { GraphStage, sceneAvailable } from "../GraphStage";
import { back, go } from "../nav";
import { approve, useApproval } from "./approvals";
import { affectedPath } from "./path";
import { metricName, STATE, storyHeadline, VERDICT, wherePhrase, whereCells } from "./plain";
import { Card, Pill, Term, useIncident } from "./ui";

interface PathCell {
  segment: Record<string, string>;
  ep: number;
  volume_share: number;
  rel_change: number;
}

const LIFECYCLE: IncidentState[] = ["open", "investigating", "explained", "monitoring", "resolved"];

/** A metric's value in its own unit: a share reads as a percentage. */
function valueText(graph: Graph | null, node: string, q: Quantity): string {
  const unit = graph?.nodes.find((n) => n.id === node)?.unit;
  if (q.unit === "value" && unit === "share") return `${(100 * q.value).toFixed(1)}%`;
  return quantity(q);
}

function series(trail: TrailStep[]): SeriesPoint[] {
  for (const s of trail) {
    const points = s.data?.series as SeriesPoint[] | undefined;
    if (Array.isArray(points) && points.length > 1) return points;
  }
  return [];
}

/** The segment search's path, keyed by the dimension each of its steps added (country, then platform, ...). */
function pathByDim(trail: TrailStep[]): Record<string, PathCell> {
  const path = (trail.find((s) => s.kind === "segment" && Array.isArray(s.data?.path))?.data.path as PathCell[] | undefined) ?? [];
  const out: Record<string, PathCell> = {};
  let before: string[] = [];
  for (const cell of path) {
    const dims = Object.keys(cell.segment);
    const added = dims.find((d) => !before.includes(d));
    if (added) out[added] = cell;
    before = dims;
  }
  return out;
}

function Step({ n, title, term, children }: { n: number; title: string; term?: string; children: React.ReactNode }) {
  return (
    <li className="ip-step">
      <span className="ip-step-n" aria-hidden="true">
        {n}
      </span>
      <div className="ip-step-body">
        <h2>{term ? <Term term={term}>{title}</Term> : title}</h2>
        {children}
      </div>
    </li>
  );
}

export function IncidentPage({ id, graph, view, onSelectNode }: { id: string; graph: Graph | null; view: RunView; onSelectNode: (id: string) => void }) {
  const summary = view.incidents[id];
  const { incident, error } = useIncident(id, summary?.lastSeq ?? 0);
  const [copied, setCopied] = useState(false);

  // Escape returns to the page the incident was opened from (demo mode closes it the same way)
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || document.querySelector(".modal, .sheet")) return;
      back();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  const copy = async () => {
    await navigator.clipboard.writeText(await api.report(id));
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1600);
  };

  return (
    <main className="fx-dash ws-page ip" aria-label={`incident ${id}`}>
      <nav className="ip-crumbs" aria-label="breadcrumb">
        <button className="ip-back" onClick={() => back()}>
          ← Back
        </button>
        <button onClick={() => go("incidents")}>Incidents</button>
        <span>/</span>
        <span className="mono">{id}</span>
      </nav>
      {!incident && <p className="fx-empty">{error ? `The incident could not be loaded: ${error}` : "Loading the incident…"}</p>}
      {incident && <Story incident={incident} graph={graph} view={view} onSelectNode={onSelectNode} copy={copy} copied={copied} />}
    </main>
  );
}

function Story({
  incident,
  graph,
  view,
  onSelectNode,
  copy,
  copied,
}: {
  incident: Incident;
  graph: Graph | null;
  view: RunView;
  onSelectNode: (id: string) => void;
  copy: () => void;
  copied: boolean;
}) {
  const f = incident.findings;
  const root = f.root;
  const node = root?.node ?? incident.root_node;
  const segment = root?.segment ?? incident.segment;
  const state = STATE[incident.state];
  const verdict = VERDICT[incident.verdict];
  const points = series(f.trail);
  const cells = pathByDim(f.trail);
  const when = (s: IncidentState) => incident.history.find((h) => h.to_state === s)?.sim_ts;
  const subject = affectedPath(view);
  const live = Boolean(graph && sceneAvailable() && subject?.incident?.id === incident.id);
  const receipts = [...new Set(f.trail.flatMap((s) => s.receipts))];
  const topFactor = [...f.decomposition].sort((a, b) => Math.abs(b.share) - Math.abs(a.share))[0];

  return (
    <>
      <header className="ip-head">
        <div className="ip-pills">
          <Pill tone={state.tone} title={state.help}>
            {state.label}
          </Pill>
          <Pill tone={verdict.tone} title={verdict.help}>
            {verdict.label}
          </Pill>
          <span className="ip-meta">
            found {dayLabel(incident.opened_at)} {hhmm(incident.opened_at)}
            {incident.resolved_at ? ` · closed ${dayLabel(incident.resolved_at)} ${hhmm(incident.resolved_at)}` : ""}
          </span>
        </div>
        <h1>{storyHeadline(graph, node, root?.change_pct.value ?? null, segment)}</h1>
        {root?.evidence && <p className="ip-cause-line">Cause: {root.evidence.description}</p>}
        <div className="ip-head-actions">
          <span className="ip-head-eur">
            <b>{eur(Math.abs(incident.severity_eur))}</b> cost so far
          </span>
          <button className="btn" onClick={copy}>
            {copied ? "Copied" : "Copy report"}
          </button>
        </div>
      </header>

      <div className="ip-grid">
        <ol className="ip-story">
          <Step n={1} title="What happened">
            <p className="ip-lead">
              At {hhmm(f.window.start)} on {dayLabel(f.window.start)}, {metricName(graph, f.observed.node).toLowerCase()} across the shop was{" "}
              <Num q={f.observed.observed} text={valueText(graph, f.observed.node, f.observed.observed)} /> where{" "}
              <Num q={f.observed.expected} text={valueText(graph, f.observed.node, f.observed.expected)} /> is usual for that hour.
              {root && (
                <>
                  {" "}
                  Most of the shop was fine: the change sits in one group, where it {root.change_pct.value < 0 ? "fell" : "rose"}{" "}
                  <Num q={root.change_pct} text={`${Math.abs(root.change_pct.value).toFixed(1)}%`} />.
                </>
              )}
            </p>
            {points.length > 1 && (
              <div className="ip-chart">
                <span className="ip-chart-cap">
                  {metricName(graph, node)} for {wherePhrase(segment)}, hour by hour, against its usual level (dashed)
                </span>
                <TimeChart points={points} onset={f.window.start} />
              </div>
            )}
          </Step>

          <Step n={2} title="Where" term="Segment search">
            <ul className="ip-where">
              {whereCells(segment).map((c) => {
                const cell = cells[c.dim];
                return (
                  <li key={c.dim}>
                    <span className="ip-where-dim">{c.name}</span>
                    <b>{c.value}</b>
                    {cell && (
                      <span className="ip-where-meta">
                        carries {(100 * cell.ep).toFixed(0)}% of the drop · {pct(100 * cell.rel_change)} here
                      </span>
                    )}
                  </li>
                );
              })}
            </ul>
            <p className="ip-note">Everything outside this group stayed in its usual range.</p>
          </Step>

          <Step n={3} title="Why">
            {root?.evidence ? (
              <div className="ip-cause">
                <span className="ip-cause-kind">{humanize(root.evidence.kind)}</span>
                <b>{root.evidence.description}</b>
                <span className="ip-cause-meta">
                  logged {hhmm(root.evidence.ts)} in {humanize(root.evidence.log.replace(/^log_/, ""))} · explains {(100 * f.explained_share).toFixed(0)}% of the drop
                </span>
              </div>
            ) : (
              <p className="ip-lead">No logged change explains it yet; {(100 * f.unexplained_share).toFixed(0)}% stays unexplained and is reported as such.</p>
            )}
            {topFactor && f.decomposed_node && (
              <p className="ip-lead">
                {metricName(graph, f.decomposed_node)} moved because of {metricName(graph, topFactor.node).toLowerCase()}: it carries{" "}
                <Num q={{ value: 100 * topFactor.share, unit: "pct", receipt: topFactor.receipt }} text={`${(100 * topFactor.share).toFixed(0)}%`} /> of the change
                {topFactor.share > 1 ? ", while the other factors moved slightly the other way" : ""} (<Term term="LMDI">exact split</Term>).
              </p>
            )}
            {f.ruled_out.length > 0 && (
              <div className="ip-ruled">
                <h3>
                  Ruled out: {f.ruled_out.length} other suspect{f.ruled_out.length === 1 ? "" : "s"}
                </h3>
                <ul>
                  {f.ruled_out.map((r) => (
                    <li key={r.hypothesis}>
                      <span className="ip-x" aria-hidden="true">
                        ✕
                      </span>
                      <div>
                        <b>{r.evidence?.description ?? r.hypothesis}</b>
                        <span>
                          {r.result === "refuted" ? "Ruled out" : "Not proven either way"}: where it applied but the problem was not, things stayed normal.{" "}
                          <Term term="Holdout">How?</Term>
                        </span>
                        <span className="ip-detail mono">{r.reason}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </Step>

          <Step n={4} title="What it costs">
            <div className="ip-cost">
              <div>
                <span>Total so far</span>
                <b>{eur(Math.abs(incident.severity_eur))}</b>
              </div>
              {f.impact && (
                <>
                  <div>
                    <span>Per hour while it lasted</span>
                    <b>
                      <Num q={{ ...f.impact.gmv_eur_per_hour, value: Math.abs(f.impact.gmv_eur_per_hour.value) }} />
                    </b>
                  </div>
                  <div>
                    <span>{metricName(graph, f.impact.node)} lost per hour</span>
                    <b>
                      <Num q={{ ...f.impact.per_hour, value: Math.abs(f.impact.per_hour.value) }} />
                    </b>
                  </div>
                </>
              )}
            </div>
            <p className="ip-note">Measured against what the same hours usually bring; every figure opens the query behind it.</p>
          </Step>

          <Step n={5} title="What to do">
            {f.suggested_action ? <Action incident={incident} view={view} /> : <p className="ip-lead">No action proposed: {verdict.help}</p>}
            {f.uncertain.length > 0 && (
              <div className="ip-open">
                <h3>Still open</h3>
                <ul>
                  {f.uncertain.map((u) => (
                    <li key={u}>{u}</li>
                  ))}
                </ul>
              </div>
            )}
          </Step>

          <Step n={6} title="Evidence" term="Receipt">
            <p className="ip-lead">
              {f.trail.length} checks, {f.cost.queries} queries in {f.cost.seconds.toFixed(2)} s, {f.cost.llm_calls} AI calls. Every number above comes from one of these
              queries; open any to see its SQL.
            </p>
            <details className="ip-evidence">
              <summary>Show every check, in order</summary>
              <ol>
                {f.trail.map((s) => (
                  <li key={s.step} className={isRuledOut(s.decision) ? "out" : undefined}>
                    <span className="ip-ev-n">{s.step}</span>
                    <div>
                      <b>{humanize(s.kind)}</b>
                      <span className="ip-ev-result">{s.result}</span>
                      <span className="ip-ev-decision">
                        {isRuledOut(s.decision) ? "✕ " : "→ "}
                        {s.decision}
                      </span>
                      <ReceiptChips ids={s.receipts} max={6} />
                    </div>
                  </li>
                ))}
              </ol>
            </details>
            <details className="ip-evidence">
              <summary>The SQL behind each number ({receipts.length})</summary>
              <ReceiptChips ids={receipts} max={receipts.length} />
            </details>
          </Step>
        </ol>

        <aside className="ip-side">
          {live && graph && (
            <Card
              title="Where it hits"
              className="fx-card-path"
              action={
                <button className="btn" onClick={() => go("graph")}>
                  Visualization
                </button>
              }
            >
              <div className="fx-path-scene">
                <GraphStage graph={graph} view={view} onSelectNode={onSelectNode} variant="preview" />
              </div>
            </Card>
          )}
          <Card title="Timeline" className="ip-timeline">
            <ol>
              {LIFECYCLE.map((s) => {
                const at = when(s);
                return (
                  <li key={s} className={`${at ? "done" : ""}${incident.state === s ? " now" : ""}`}>
                    <i aria-hidden="true" />
                    <b>{STATE[s].label}</b>
                    <span className="mono">{at ? `${dayLabel(at)} ${hhmm(at)}` : "–"}</span>
                    <span className="ip-tl-help">{STATE[s].help}</span>
                  </li>
                );
              })}
            </ol>
          </Card>
          {!live && (
            <Card title="See it on the map" className="ip-map">
              <p className="fx-card-note">
                {incident.state === "resolved"
                  ? "The incident is closed, so the map shows the shop as it is now."
                  : "The 3D map shows the affected metrics while the incident is open."}
              </p>
              <button className="btn" onClick={() => go("graph")}>
                Open visualization
              </button>
            </Card>
          )}
        </aside>
      </div>
    </>
  );
}

function Action({ incident, view }: { incident: Incident; view: RunView }) {
  const approvedAt = useApproval(view.stream, incident.id);
  const action = incident.findings.suggested_action;
  if (!action) return null;
  return (
    <div className="ip-action">
      <p>
        <span>Proposed</span>
        {action.text.replace(/\.?$/, ".")}
      </p>
      <div className="ip-action-foot">
        {approvedAt ? (
          <span className="ws-approved">✓ Approved at {hhmm(approvedAt)}, handed to your team</span>
        ) : incident.state === "resolved" ? (
          <span className="ws-task-note">Recovered on its own; no action needed any more.</span>
        ) : (
          <button className="btn primary" onClick={() => approve(view.stream, incident.id, view.simTs ?? "")}>
            Approve action
          </button>
        )}
        <span className="ip-note">{action.needs_approval ? "Argus never changes the business by itself: this waits for you." : "Safe to run automatically."}</span>
      </div>
    </div>
  );
}
