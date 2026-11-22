import { Fragment, useId, useState, type CSSProperties } from "react";
import { ReceiptChips } from "../../components/Receipts";
import { Card } from "../../fx/workspace/ui";
import { hhmm } from "../../lib/format";
import type { GraphNode, Incident, Quantity } from "../../lib/types";
import { HISTORY_PERIODS, dateTime, metricValue, time, type AnalyticsPeriod, type AnalyticsWindow, type HistoryMarker, type HistoryPoint } from "./model";

interface HistoricalMetricsProps {
  metric: GraphNode;
  scope: string;
  period: AnalyticsPeriod;
  window: AnalyticsWindow;
  points: HistoryPoint[];
  markers: HistoryMarker[];
  incident?: Incident;
  change?: Quantity | null;
  onPeriodChange?: (period: AnalyticsPeriod) => void;
  incidentHref?: (id: string) => string;
  stream?: string | null;
}

const SERIES = [
  ["observed", "Observed"],
  ["expected", "Expected"],
  ["band", "Expected range"],
] as const;
type SeriesKey = (typeof SERIES)[number][0];
const HOUR = 3_600_000;
const shortTime = (at: number) => hhmm(new Date(at).toISOString());
const day = new Intl.DateTimeFormat("en-GB", { day: "numeric", month: "short", timeZone: "UTC" });

function plotBounds(points: HistoryPoint[]) {
  const values = points.flatMap(({ observed, expected, band }) => [observed, expected, ...(band ?? [])])
    .filter((value): value is number => value !== null);
  if (!values.length) return null;
  const lo = Math.min(...values);
  const hi = Math.max(...values);
  const spread = hi - lo || Math.max(Math.abs(hi) * 0.01, 0.01);
  return { min: lo - spread / 4, max: hi + spread / 4 };
}

function HistoryPlot({
  metric, points, markers, marker, visible, incident, window,
}: Pick<HistoricalMetricsProps, "metric" | "points" | "markers" | "incident" | "window"> & {
  marker: HistoryMarker | undefined;
  visible: Record<SeriesKey, boolean>;
}) {
  const opens = time(incident?.opened_at);
  const closes = time(incident?.resolved_at) ?? window.end;
  const bounds = plotBounds(points);
  const dates = [...points.map(({ at }) => at), ...markers.map(({ at }) => at)];
  if (opens !== null && window.end !== null && opens <= window.end) {
    dates.push(Math.max(opens, window.start ?? opens));
    if (closes !== null) dates.push(closes);
  }
  if (!dates.length) return null;
  const first = Math.min(...dates);
  const last = Math.max(...dates);
  const pad = Math.max((last - first) * 0.03, 60_000);
  const minAt = first - pad;
  const maxAt = last + pad;
  const x = (at: number) => ((at - minAt) / (maxAt - minAt)) * 100;
  const y = (value: number) => bounds ? ((bounds.max - value) / (bounds.max - bounds.min)) * 100 : 50;
  const stylesAt = (at: number, value?: number): CSSProperties => ({
    left: `${x(at)}%`, ...(value === undefined ? {} : { top: `${y(value)}%` }),
  });
  const candidates = bounds ? [bounds.max, (bounds.min + bounds.max) / 2, bounds.min] : [];
  const tickLabels = new Set(candidates.map((tick) => metricValue(tick, metric.unit)));
  const yTicks = tickLabels.size === 1 ? [candidates[1]] : tickLabels.size === 2 ? [candidates[0], candidates[2]] : candidates;
  const sameDay = day.format(first) === day.format(last) && last - first < 24 * HOUR;
  const xLabel = (at: number) => sameDay ? shortTime(at) : `${day.format(at)} ${shortTime(at)}`;
  const path = (key: "observed" | "expected") => points.map((point, index) => {
    const value = point[key];
    if (value === null) return "";
    const before = points[index - 1];
    const join = before && before[key] !== null && point.at - before.at === HOUR;
    return `${join ? "L" : "M"}${x(point.at)},${y(value)}`;
  }).join(" ");

  const left = opens === null ? null : Math.max(opens, minAt);
  const right = closes === null ? null : Math.min(closes, maxAt);

  return (
    <div className="an-history-chart" aria-hidden="true">
      <div className="an-axis-y" data-single={yTicks.length === 1 || undefined}>
        {yTicks.map((tick) => <span key={tick}>{metricValue(tick, metric.unit)}</span>)}
      </div>
      <div className="an-chart-area">
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="an-chart-lines">
          {yTicks.map((tick) => <line key={tick} x1="0" x2="100" y1={y(tick)} y2={y(tick)} className="an-grid-line" />)}
          {left !== null && right !== null && left <= right && (
            <rect className="an-incident-span" x={x(left)} y="0" width={x(right) - x(left)} height="100" />
          )}
          {(["expected", "observed"] as const).map((key) => visible[key] && (
            <path key={key} d={path(key)} className={`an-series-line is-${key}`} />
          ))}
        </svg>
        {markers.map((event) => (
          <span key={event.id} className={`an-marker is-${event.kind}${marker?.id === event.id ? " is-active" : ""}`} style={stylesAt(event.at)} />
        ))}
        {points.map(({ at, observed, expected, band }) => (
          <div key={at}>
            {visible.band && band && (
              <span className="an-band" style={{ ...stylesAt(at, band[1]), height: `${y(band[0]) - y(band[1])}%` }} />
            )}
            {visible.expected && expected !== null && <span className="an-dot is-expected" style={stylesAt(at, expected)} />}
            {visible.observed && observed !== null && <span className="an-dot is-observed" style={stylesAt(at, observed)} />}
          </div>
        ))}
      </div>
      <div className="an-axis-x">
        <span>{xLabel(first)}</span>
        <span>{first === last ? "UTC" : `${xLabel(last)} UTC`}</span>
      </div>
    </div>
  );
}

export function HistoricalMetrics(props: HistoricalMetricsProps) {
  const { metric, scope, period, window, points, markers, change, onPeriodChange, incidentHref, stream } = props;
  const [visible, setVisible] = useState<Record<SeriesKey, boolean>>({ observed: true, expected: true, band: true });
  const [active, setActive] = useState<{ id: string; stream: typeof stream }>();
  const marker = active?.stream === stream ? markers.find(({ id }) => id === active?.id) : undefined;
  const eventDetail = useId();
  const first = points[0];
  const last = points.at(-1);
  const releaseOnly = markers.length > 0 && !first;
  const start = window.start === null ? "All retained evidence" : dateTime(window.start);
  const units = metric.unit === "share" || metric.unit === "pct" ? "%" : metric.unit === "ratio" ? "×" : metric.unit.replaceAll("_", " ");

  const periods = onPeriodChange && (
    <div className="an-periods" role="group" aria-label="Historical metrics period">
      {HISTORY_PERIODS.map(([id, label]) => (
        <button key={id} type="button" aria-pressed={period === id} onClick={() => onPeriodChange(id)}>{label}</button>
      ))}
    </div>
  );

  return (
    <Card title="Historical Metrics" className="an-card an-history" action={periods}>
      <div className="an-context">
        <strong>{metric.label} · {scope}</strong>
        <span>{window.end === null ? "Waiting for the run clock" : `${start} → ${dateTime(window.end)}`}</span>
      </div>
      {first ? (
        <fieldset className="an-legend">
          <legend className="an-sr-only">Visible chart series</legend>
          {SERIES.map(([id, label]) => {
            const available = points.some((point) => point[id] !== null);
            return (
              <label key={id} className={`is-${id}`}>
                <input type="checkbox" name={id} checked={visible[id] && available} disabled={!available}
                  onChange={(event) => setVisible({ ...visible, [id]: event.target.checked })} />
                {label}
              </label>
            );
          })}
        </fieldset>
      ) : <p className="fx-empty">No measured samples in this scope and period.{releaseOnly ? " Recorded events are shown below." : ""}</p>}
      <HistoryPlot {...props} marker={marker} visible={visible} />
      {markers.length > 0 && (
        <div className="an-events" role="group" aria-label="Timeline events">
          {markers.map((event, index) => {
            const selected = event.id === marker?.id;
            const detailId = `${eventDetail}-${index}`;
            const select = () => setActive({ id: event.id, stream });
            return (
              <Fragment key={event.id}>
                <button type="button" className={`is-${event.kind}`} aria-pressed={selected} aria-controls={detailId}
                  onFocus={select} onClick={select}>
                  {event.label} <time dateTime={new Date(event.at).toISOString()}>{shortTime(event.at)}</time>
                </button>
                <div id={detailId} className="an-event-detail" hidden={!selected}>
                  {selected && (
                    <>
                      <p><strong>{dateTime(event.at)}</strong> · {event.detail}</p>
                      <ReceiptChips ids={[...event.receipts]} />
                      {event.kind === "incident" && incidentHref && <a href={incidentHref(event.id)}>Open {event.id}</a>}
                    </>
                  )}
                </div>
              </Fragment>
            );
          })}
        </div>
      )}
      {first && last && (
        <details className="an-samples">
          <summary>{points.length === 1 ? `1 measured hour · ${dateTime(first.at)}` : `${points.length} measured hours · ${dateTime(first.at)} → ${dateTime(last.at)}`}
            {points.length === 1 && first.observed !== null && <span> · {metricValue(first.observed, metric.unit)} observed</span>}
          </summary>
          <div className="an-table-scroll" tabIndex={0} role="region" aria-label="Measured history samples">
            <table>
              <thead><tr><th scope="col">Hour (UTC)</th><th scope="col">Observed ({units})</th><th scope="col">Expected ({units})</th><th scope="col">Expected range ({units})</th><th scope="col">Evidence</th></tr></thead>
              <tbody>
                {points.map(({ at, observed, expected, band, receipts }) => (
                  <tr key={at}>
                    <th scope="row">{dateTime(at)}</th>
                    <td>{observed === null ? "—" : metricValue(observed, metric.unit)}</td>
                    <td>{expected === null ? "—" : metricValue(expected, metric.unit)}</td>
                    <td>{band ? band.map((value) => metricValue(value, metric.unit)).join(" to ") : "—"}</td>
                    <td><ReceiptChips ids={[...receipts]} /></td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </details>
      )}
      {change && !first && (
        <p className="an-context">
          <span>Incident finding · {metricValue(change.value, change.unit)} versus expected in the affected segment</span>
          {change.receipt && <ReceiptChips ids={[change.receipt]} />}
        </p>
      )}
      <p className="an-source">Source: Argus investigation evidence. Whole-period metric history is unavailable.</p>
    </Card>
  );
}
