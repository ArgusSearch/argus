import type { ReactNode } from "react";
import { Num } from "../../components/Receipts";
import { count, eur, share, segmentLabel } from "../../lib/format";
import type { IncidentView, RunView } from "../../lib/store";
import type { Anomaly, Graph, Incident } from "../../lib/types";
import { dimensionName, metricName, valueName } from "../../fx/workspace/plain";
import { Card, Pill, useIncidents } from "../../fx/workspace/ui";
import { dateTime, time } from "../analytics/model";
import { visibleFindings, type AnalysisWindow } from "../pages/model";
import {
  compareRecent, deviationHistory, driverDecomposition, funnelStages, hourlyTrend, incidentCohorts, level, metricInputs,
  segmentBreakdown, type DriverDecomposition, type PeriodStats,
} from "./model";
import "./insights.css";

export type Linker = (label: ReactNode, change: { metric?: string; segment?: Record<string, string> }) => ReactNode;

const hourLabel = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC" });
const dayOnly = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "numeric", month: "short", timeZone: "UTC" });

function Empty({ children }: { children: ReactNode }) {
  return <p className="fx-empty">{children}</p>;
}

const windowText = (ts: string) => {
  const at = time(ts);
  return at === null ? ts : dateTime(at);
};

const zText = (z: number | null) => (z === null ? "—" : z.toFixed(1));

/* Detection trend ------------------------------------------------------------------------------------------------ */

const W = 640;
const H = 160;
const PAD_L = 34;
const PAD_R = 8;
const PAD_T = 10;
const PAD_B = 22;

export function DetectionTrend({ graph, view, window, metric }: { graph: Graph | null; view: RunView; window: AnalysisWindow; metric: string }) {
  const points = hourlyTrend(view.hours, view.thresholds, window, metric);
  const scored = points.filter((point) => point.peak !== null);
  const title = metric ? `Deviation trend · ${metricName(graph, metric)}` : "Detection trend";
  if (scored.length < 2) {
    return <Card title={title} className="in-card"><Empty>{window.end === null ? "Waiting for run data." : "Fewer than two scored hours in this period."}</Empty></Card>;
  }
  const { wiggle_z: wiggle, alarm_z: alarm } = view.thresholds;
  const top = Math.max(alarm * 1.15, ...scored.map((point) => point.peak as number));
  const first = points[0].at;
  const last = points[points.length - 1].at;
  const x = (at: number) => PAD_L + ((at - first) / Math.max(last - first, 1)) * (W - PAD_L - PAD_R);
  const y = (z: number) => PAD_T + (1 - z / top) * (H - PAD_T - PAD_B);
  // A missing hour breaks the line instead of being bridged.
  let line = "";
  let previous: number | null = null;
  for (const point of points) {
    if (point.peak === null) {
      previous = null;
      continue;
    }
    const gap = previous !== null && point.at - previous > 3_600_000 * 1.5;
    line += `${line && !gap ? "L" : "M"}${x(point.at).toFixed(1)},${y(point.peak).toFixed(1)}`;
    previous = point.at;
  }
  const peak = scored.reduce((best, point) => ((point.peak as number) > (best.peak as number) ? point : best));
  const alarmHours = scored.filter((point) => (point.peak as number) >= alarm).length;
  const watchHours = scored.filter((point) => (point.peak as number) >= wiggle && (point.peak as number) < alarm).length;
  const openPeak = Math.max(...points.map((point) => point.open));
  const label = `${title}: ${scored.length} scored hours, highest deviation ${zText(peak.peak)} at ${dateTime(peak.at)}, ${alarmHours} hours at or above the alarm threshold.`;
  return (
    <Card title={title} className="in-card">
      <div className="in-kpis">
        <dl><dt>Highest |z|</dt><dd>{zText(peak.peak)}</dd></dl>
        <dl><dt>Hours in watch range</dt><dd>{count(watchHours)}</dd></dl>
        <dl><dt>Hours at alarm</dt><dd>{count(alarmHours)}</dd></dl>
        <dl><dt>Most open incidents</dt><dd>{count(openPeak)}</dd></dl>
      </div>
      <svg className="in-trend" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={label} preserveAspectRatio="none">
        {[[wiggle, "watch"], [alarm, "alarm"]].map(([z, tone]) => (
          <g key={tone}>
            <line className={`in-threshold t-${tone}`} x1={PAD_L} x2={W - PAD_R} y1={y(z as number)} y2={y(z as number)} />
            <text className="in-axis" x={PAD_L - 6} y={y(z as number) + 3} textAnchor="end">{(z as number).toFixed(1)}</text>
          </g>
        ))}
        <text className="in-axis" x={PAD_L - 6} y={y(0) + 3} textAnchor="end">0</text>
        <line className="in-base" x1={PAD_L} x2={W - PAD_R} y1={y(0)} y2={y(0)} />
        <path className="in-line" d={line} />
        {scored.filter((point) => (point.peak as number) >= wiggle).map((point) => (
          <circle key={point.at} className={`in-dot t-${level(point.peak as number, view.thresholds)}`} cx={x(point.at)} cy={y(point.peak as number)} r={3} />
        ))}
        <text className="in-axis" x={PAD_L} y={H - 6}>{hourLabel.format(first)}</text>
        <text className="in-axis" x={W - PAD_R} y={H - 6} textAnchor="end">{hourLabel.format(last)} UTC</text>
      </svg>
      <p className="fx-card-note">
        Highest |z| per scored hour{metric ? "" : " across the scored metrics"}, from the active stream. Dashed lines mark the watch ({wiggle.toFixed(1)}) and alarm ({alarm.toFixed(1)}) thresholds.
      </p>
    </Card>
  );
}

/* Period comparison ---------------------------------------------------------------------------------------------- */

type Row = [label: string, read: (stats: PeriodStats) => number | null, format: (value: number) => string, delta: (value: number) => string];

const signed = (value: number, text: string) => `${value > 0 ? "+" : value < 0 ? "−" : "±"}${text}`;
const ROWS: Row[] = [
  ["Scored hours", (s) => s.hours, count, (d) => signed(d, count(Math.abs(d)))],
  ["Mean of hourly highest |z|", (s) => s.meanPeak, (v) => v.toFixed(2), (d) => signed(d, Math.abs(d).toFixed(2))],
  ["Highest |z|", (s) => s.peak, (v) => v.toFixed(1), (d) => signed(d, Math.abs(d).toFixed(1))],
  ["Hours in watch range or above", (s) => s.watchHours, count, (d) => signed(d, count(Math.abs(d)))],
  ["Hours at alarm", (s) => s.alarmHours, count, (d) => signed(d, count(Math.abs(d)))],
  ["Anomalies opened", (s) => s.anomalies, count, (d) => signed(d, count(Math.abs(d)))],
  ["Incidents opened", (s) => s.incidentsOpened, count, (d) => signed(d, count(Math.abs(d)))],
  ["Lowest data completeness", (s) => s.minCompleteness, (v) => share(v), (d) => `${signed(d, (100 * Math.abs(d)).toFixed(0))} pp`],
];

export function PeriodComparison({ graph, view, metric, segment, span = 24 }: {
  graph: Graph | null; view: RunView; metric: string; segment: Record<string, string>; span?: number;
}) {
  const comparison = compareRecent(view, metric, segment, span);
  const title = `Latest ${span} hours vs the ${span} before`;
  if (!comparison || !comparison.current.hours) return <Card title={title} className="in-card"><Empty>Waiting for scored hours.</Empty></Card>;
  const { current, previous } = comparison;
  return (
    <Card title={title} className="in-card">
      <div className="analysis-table-scroll" tabIndex={0} role="region" aria-label="Period comparison table">
        <table className="analysis-table in-compare">
          <thead>
            <tr>
              <th scope="col">{metric ? metricName(graph, metric) : "All scored metrics"}{Object.keys(segment).length > 0 && <span>{segmentLabel(segment)}</span>}</th>
              <th scope="col" className="analysis-number">Latest {span} h</th>
              <th scope="col" className="analysis-number">Previous {span} h</th>
              <th scope="col" className="analysis-number">Change</th>
            </tr>
          </thead>
          <tbody>
            {ROWS.map(([label, read, format, delta]) => {
              const now = read(current);
              const before = previous ? read(previous) : null;
              const diff = now !== null && before !== null ? now - before : null;
              return (
                <tr key={label}>
                  <th scope="row">{label}</th>
                  <td className="analysis-number">{now === null ? "—" : format(now)}</td>
                  <td className="analysis-number">{before === null ? "—" : format(before)}</td>
                  <td className="analysis-number">{diff === null ? "—" : delta(Math.abs(diff) < 1e-9 ? 0 : diff)}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
      <p className="fx-card-note">
        {previous
          ? `Ending ${dateTime(current.to)}. ${previous.hours < span ? `The previous period holds ${previous.hours} of ${span} scored hours.` : "Both periods are fully scored."}`
          : "The stream holds no scored hour before the latest period yet."}
        {metric && Object.keys(segment).length > 0 && " Scores are whole-shop; anomaly and incident counts follow the segment."}
      </p>
    </Card>
  );
}

/* Deviation history ---------------------------------------------------------------------------------------------- */

export function DeviationHistory({ graph, view, window, order, only, link }: {
  graph: Graph | null; view: RunView; window: AnalysisWindow; order: readonly string[]; only?: readonly string[]; link: Linker;
}) {
  const { columns, rows } = deviationHistory(view, window, order, only);
  if (!columns.length || !rows.length) {
    return <Card title="Deviation history" className="in-card"><Empty>{window.end === null ? "Waiting for run data." : "No scored hours in this period."}</Empty></Card>;
  }
  const days = columns.flatMap((at, index) => (index === 0 || new Date(at).getUTCDate() !== new Date(columns[index - 1]).getUTCDate() ? [{ at, index }] : []));
  return (
    <Card title="Deviation history" className="in-card">
      <div className="in-heat-scroll" tabIndex={0} role="region" aria-label="Deviation history by metric and hour">
        <table className="in-heat" style={{ ["--cols" as string]: columns.length }}>
          <thead>
            <tr>
              <th scope="col">Metric</th>
              <td className="in-heat-days" aria-hidden="true">
                {days.map(({ at, index }) => (
                  <span key={at} style={{ gridColumnStart: index + 1 }}>{dayOnly.format(at)}</span>
                ))}
              </td>
              <th scope="col" className="analysis-number">Peak</th>
              <th scope="col" className="analysis-number">Anomalies</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.metric}>
                <th scope="row">{link(metricName(graph, row.metric), { metric: row.metric })}</th>
                <td className="in-heat-cells">
                  {row.cells.map((cell) => (
                    <i key={cell.at} className={cell.z === null ? "t-none" : `t-${level(cell.z, view.thresholds)}`} data-flag={cell.flagged || undefined}
                      style={cell.z === null ? undefined : { ["--z" as string]: Math.min(cell.z / view.thresholds.alarm_z, 1) }}
                      title={`${hourLabel.format(cell.at)} UTC · ${cell.z === null ? "not scored" : `|z| ${cell.z.toFixed(2)}`}${cell.flagged ? " · anomaly opened" : ""}`} />
                  ))}
                </td>
                <td className="analysis-number">{zText(row.peak)}</td>
                <td className="analysis-number">{count(row.anomalies)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <p className="fx-card-note in-legend">
        <span><i className="t-calm" /> below watch</span>
        <span><i className="t-watch" /> watch range</span>
        <span><i className="t-alarm" /> alarm</span>
        <span><i className="t-calm" data-flag /> anomaly opened</span>
        <span>One cell per scored hour, {columns.length} hours shown.</span>
      </p>
    </Card>
  );
}

/* Segment breakdown ---------------------------------------------------------------------------------------------- */

export function SegmentBreakdown({ signals, incidents, link, window }: {
  signals: readonly Anomaly[]; incidents: readonly IncidentView[]; link: Linker; window: AnalysisWindow;
}) {
  const { rows, wholeShop } = segmentBreakdown(signals, incidents);
  const maxImpact = Math.max(...rows.map((row) => row.impact), 0);
  const maxCount = Math.max(...rows.map((row) => row.anomalies + row.incidents), 0);
  return (
    <Card title="Segment breakdown" className="in-card">
      {window.end === null ? <Empty>Waiting for run data.</Empty> : !rows.length ? (
        <Empty>No segment appears in the matching anomalies or incidents{wholeShop ? `; ${wholeShop} whole-shop ${wholeShop === 1 ? "anomaly" : "anomalies"}` : ""}.</Empty>
      ) : (
        <div className="analysis-table-scroll" tabIndex={0} role="region" aria-label="Segment breakdown table">
          <table className="analysis-table">
            <thead>
              <tr>
                <th scope="col">Segment</th>
                <th scope="col" className="analysis-number">Anomalies</th>
                <th scope="col" className="analysis-number">Falls / rises</th>
                <th scope="col" className="analysis-number">Peak |z|</th>
                <th scope="col" className="analysis-number">Incidents</th>
                <th scope="col" className="in-bar-col">Incident impact</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((row) => {
                const weight = maxImpact > 0 ? row.impact / maxImpact : maxCount > 0 ? (row.anomalies + row.incidents) / maxCount : 0;
                return (
                  <tr key={`${row.dimension}:${row.value}`}>
                    <th scope="row">{link(valueName(row.dimension, row.value), { segment: { [row.dimension]: row.value } })}<span>{dimensionName(row.dimension)}</span></th>
                    <td className="analysis-number">{count(row.anomalies)}</td>
                    <td className="analysis-number">{count(row.falls)} / {count(row.rises)}</td>
                    <td className="analysis-number">{zText(row.peakZ)}</td>
                    <td className="analysis-number">{count(row.incidents)}</td>
                    <td className="in-bar-col">
                      <span className="in-bar"><i style={{ inlineSize: `${Math.max(weight * 100, row.impact ? 2 : 0)}%` }} /></span>
                      <span className="in-bar-value">{row.incidents ? eur(row.impact) : "—"}</span>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
      {rows.length > 0 && <p className="fx-card-note">Counts come from the anomalies and incidents in this query; one event counts once in every dimension of its scope.{wholeShop ? ` ${wholeShop} whole-shop ${wholeShop === 1 ? "anomaly has" : "anomalies have"} no segment.` : ""}</p>}
    </Card>
  );
}

/* Incident cohorts ----------------------------------------------------------------------------------------------- */

export function IncidentCohorts({ incidents, window }: { incidents: readonly IncidentView[]; window: AnalysisWindow }) {
  const cohorts = incidentCohorts(incidents);
  return (
    <Card title="Incident cohorts" className="in-card">
      {window.end === null ? <Empty>Waiting for run data.</Empty> : !cohorts.length ? <Empty>No incidents match this query.</Empty> : (
        <div className="analysis-table-scroll" tabIndex={0} role="region" aria-label="Incident cohorts table">
          <table className="analysis-table">
            <thead>
              <tr>
                <th scope="col">Day (UTC)</th>
                <th scope="col" className="analysis-number">Opened</th>
                <th scope="col" className="in-bar-col">Status now</th>
                <th scope="col" className="analysis-number">To resolve</th>
                <th scope="col" className="analysis-number">Impact</th>
              </tr>
            </thead>
            <tbody>
              {cohorts.map((cohort) => (
                <tr key={cohort.day}>
                  <th scope="row">{dayOnly.format(Date.parse(`${cohort.day}T00:00:00Z`))}</th>
                  <td className="analysis-number">{count(cohort.opened)}</td>
                  <td className="in-bar-col">
                    <span className="in-stack" aria-hidden="true">
                      {cohort.active > 0 && <i className="t-alarm" style={{ flexGrow: cohort.active }} />}
                      {cohort.explained > 0 && <i className="t-watch" style={{ flexGrow: cohort.explained }} />}
                      {cohort.resolved > 0 && <i className="t-ok" style={{ flexGrow: cohort.resolved }} />}
                    </span>
                    <span className="in-bar-value">{([[cohort.active, "active"], [cohort.explained, "explained"], [cohort.resolved, "resolved"]] as const)
                      .filter(([n]) => n > 0).map(([n, word]) => `${n} ${word}`).join(" · ")}</span>
                  </td>
                  <td className="analysis-number">{cohort.hoursToResolve === null ? "—" : `${cohort.hoursToResolve.toFixed(1)} h`}</td>
                  <td className="analysis-number">{eur(cohort.impact)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      {cohorts.length > 0 && <p className="fx-card-note">Incidents grouped by the day they opened. Active covers open and investigating; explained covers explained and monitoring. To resolve is the mean time from opening to resolution. Impact is the summed incident severity.</p>}
    </Card>
  );
}

/* Driver decomposition ------------------------------------------------------------------------------------------- */

function DriverBars({ graph, drivers }: { graph: Graph | null; drivers: DriverDecomposition }) {
  const unit = graph?.nodes.find((node) => node.id === drivers.node)?.unit ?? "count";
  const max = Math.max(...drivers.rows.map((row) => Math.abs(row.share)), 1e-9);
  return (
    <ul className="in-drivers">
      {drivers.rows.map((row) => (
        <li key={row.node}>
          <span className="in-driver-name">{metricName(graph, row.node)}</span>
          <span className="in-diverge" aria-hidden="true">
            <i data-side={row.share < 0 ? "neg" : "pos"} style={{ inlineSize: `${(Math.abs(row.share) / max) * 50}%` }} />
          </span>
          <span className="in-driver-share">{share(row.share, 1)}</span>
          <span className="in-driver-value"><Num q={{ value: row.value, unit: unit === "eur" ? "eur" : "count", receipt: row.receipt }} signed /></span>
        </li>
      ))}
    </ul>
  );
}

export function DriverDecompositionCard({ graph, incidents, metric, incidentLink }: {
  graph: Graph | null; incidents: readonly Incident[]; metric: string; incidentLink: (id: string) => ReactNode;
}) {
  const drivers = driverDecomposition(incidents, metric);
  return (
    <Card title="Driver decomposition" className="in-card">
      {!drivers ? <Empty>No recorded decomposition {metric ? `involves ${metricName(graph, metric)}` : "is visible"} at this point in the run.</Empty> : (
        <>
          <p className="in-lede">
            Change in <strong>{metricName(graph, drivers.node)}</strong>{Object.keys(drivers.segment).length > 0 && ` for ${segmentLabel(drivers.segment)}`}, split by input · {incidentLink(drivers.incidentId)}
          </p>
          <DriverBars graph={graph} drivers={drivers} />
          <p className="fx-card-note">
            {drivers.window.start === drivers.window.end
              ? `Shares of the measured change in the hour of ${windowText(drivers.window.end)}.`
              : `Shares of the measured change from ${windowText(drivers.window.start)} to ${windowText(drivers.window.end)}.`}
            {" "}Explained {share(drivers.explainedShare)}, unexplained {share(drivers.unexplainedShare)}. Negative shares moved against the change. Values open their query.
          </p>
        </>
      )}
    </Card>
  );
}

/* Metric inputs -------------------------------------------------------------------------------------------------- */

export function MetricInputs({ graph, view, metric, link }: { graph: Graph | null; view: RunView; metric: string; link: Linker }) {
  const inputs = metricInputs(graph, view, metric);
  const node = graph?.nodes.find((candidate) => candidate.id === metric);
  return (
    <Card title="Inputs of this metric" className="in-card">
      {!inputs.length ? (
        <Empty>{node?.table ? `${node.label} is measured directly from ${node.table}.` : "The graph defines no formula or causal input for this metric."}</Empty>
      ) : (
        <div className="analysis-table-scroll" tabIndex={0} role="region" aria-label="Metric inputs table">
          <table className="analysis-table">
            <thead>
              <tr>
                <th scope="col">Input</th>
                <th scope="col">Relationship</th>
                <th scope="col" className="analysis-number">Latest |z|</th>
                <th scope="col" className="analysis-number">Median test error</th>
              </tr>
            </thead>
            <tbody>
              {inputs.map((input) => (
                <tr key={`${input.edge}:${input.node}`}>
                  <th scope="row">{link(metricName(graph, input.node), { metric: input.node })}<span>{input.kind === "formula" ? "Formula input" : "Proposed cause"}</span></th>
                  <td><Pill tone={input.status === "BROKEN" ? "alarm" : input.status === "VALID" || input.status === "SUPPORTED" ? "ok" : "muted"}>{input.status.toLowerCase()}</Pill></td>
                  <td className="analysis-number">{input.z === null ? "not scored hourly" : input.z.toFixed(1)}</td>
                  <td className="analysis-number">{input.medianError === null ? "—" : share(input.medianError, 2)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

/* Funnel --------------------------------------------------------------------------------------------------------- */

export function FunnelStages({ graph, view, steps, window, incidents, link }: {
  graph: Graph | null; view: RunView; steps: readonly string[]; window: AnalysisWindow; incidents: readonly Incident[]; link: Linker;
}) {
  const drivers = driverDecomposition(incidents, "orders");
  const stages = funnelStages(graph, view, steps, window, drivers);
  if (!stages.length) return <Card title="Funnel stages" className="in-card"><Empty>Waiting for the metric graph.</Empty></Card>;
  const max = Math.max(...stages.map((stage) => Math.abs(stage.contribution?.share ?? 0)), 1e-9);
  return (
    <Card title="Funnel stages" className="in-card">
      <ol className="in-funnel">
        {stages.map((stage, index) => (
          <li key={stage.node}>
            <span className="in-funnel-step">{index + 1}</span>
            <div>
              <strong>{link(metricName(graph, stage.node), { metric: stage.node })}</strong>
              {stage.rate && <span>from previous step: {link(metricName(graph, stage.rate), { metric: stage.rate })}</span>}
            </div>
            <dl>
              <dt>Latest |z|</dt>
              <dd>{stage.z !== null ? stage.z.toFixed(1) : stage.rateZ !== null ? `${stage.rateZ.toFixed(1)} (rate)` : "not scored hourly"}</dd>
            </dl>
            <dl>
              <dt>Anomalies</dt>
              <dd>{count(stage.anomalies)}</dd>
            </dl>
            <div className="in-funnel-share">
              <span className="in-diverge" aria-hidden="true">
                {stage.contribution && <i data-side={stage.contribution.share < 0 ? "neg" : "pos"} style={{ inlineSize: `${(Math.abs(stage.contribution.share) / max) * 50}%` }} />}
              </span>
              <span>{stage.contribution ? `${share(stage.contribution.share, 1)} of order change` : "—"}</span>
            </div>
          </li>
        ))}
      </ol>
      <p className="fx-card-note">
        {drivers ? `Shares come from the latest recorded order decomposition (${drivers.incidentId}).` : "No order decomposition is recorded yet, so no stage shares are shown."}
        {" "}Only metrics the watcher scores every hour carry a |z|.
      </p>
    </Card>
  );
}

/** The incidents whose findings are visible at the current point of the run, read once for the cards below it. */
export function VisibleIncidents({ view, window, children }: {
  view: RunView; window: AnalysisWindow; children: (incidents: Incident[]) => ReactNode;
}) {
  const { incidents } = useIncidents(view);
  return <>{children(incidents.filter((incident) => visibleFindings(incident, view.incidents[incident.id], window)))}</>;
}
