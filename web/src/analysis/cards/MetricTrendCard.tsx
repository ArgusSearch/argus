import { useEffect, useId, useState, type CSSProperties } from "react";
import { CardEmpty, CardFrame, type CardProps } from "./AnalysisCards";
import { chartPoints, formatValue, runs, timestamp, type CardUnit, type ChartEvent, type ChartPoint } from "./model";

const WIDTH = 500;
const HEIGHT = 120;
const PAD = 16;
const dateTime = new Intl.DateTimeFormat("en-GB", {
  day: "numeric", month: "short", hour: "2-digit", minute: "2-digit", timeZone: "UTC",
});
const clock = new Intl.DateTimeFormat("en-GB", { hour: "2-digit", minute: "2-digit", timeZone: "UTC" });

function EventTooltip({ event, time }: { event: ChartEvent; time: number }) {
  const id = useId();
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [dismissed, setDismissed] = useState(false);
  const open = (hovered || focused || pinned) && !dismissed;
  useEffect(() => {
    if (!open) return;
    const dismiss = (key: KeyboardEvent) => {
      if (key.key === "Escape") {
        setPinned(false);
        setDismissed(true);
      }
    };
    window.addEventListener("keydown", dismiss);
    return () => window.removeEventListener("keydown", dismiss);
  }, [open]);
  return (
    <div className="ac-event" onPointerLeave={() => setHovered(false)}>
      <button
        className="ac-event-button"
        type="button"
        aria-describedby={id}
        onPointerEnter={(pointer) => {
          if (pointer.pointerType !== "touch") {
            setHovered(true);
            setDismissed(false);
          }
        }}
        onFocus={(focus) => {
          setFocused(focus.currentTarget.matches(":focus-visible"));
          setDismissed(false);
        }}
        onBlur={() => {
          setFocused(false);
          setPinned(false);
        }}
        onClick={() => {
          setPinned(!pinned);
          setDismissed(pinned);
        }}
      >
        <span className="ac-key ac-key-event" aria-hidden="true" />
        {event.label}
      </button>
      <div id={id} role="tooltip" hidden={!open} className="ac-event-tooltip">
        <time dateTime={new Date(time).toISOString()}>{dateTime.format(time)} UTC</time>
        <p>{event.detail}</p>
      </div>
    </div>
  );
}

export interface MetricTrendCardProps extends CardProps {
  unit: CardUnit;
  points: readonly ChartPoint[];
  /** Longest interval that may join two adjacent observations. Omit for isolated observations. */
  maxGapMs?: number;
  event?: ChartEvent;
}

export function MetricTrendCard({ unit, points, event, maxGapMs = 0, ...card }: MetricTrendCardProps) {
  const samples = chartPoints(points, unit);
  const observed = runs(samples.map((point) => ({ time: point.time, value: point.observed })), maxGapMs);
  if (!observed.length) {
    return <CardFrame {...card}><CardEmpty>{card.empty}</CardEmpty></CardFrame>;
  }

  const expected = runs(samples.map((point) => ({ time: point.time, value: point.expected ?? null })), maxGapMs);
  const bands = runs(samples.map((point) => ({ time: point.time, value: point.band ?? null })), maxGapMs);
  const eventTime = event ? timestamp(event.at) : NaN;
  const validEvent = event && Number.isFinite(eventTime) ? event : null;
  const times = validEvent ? [...samples.map((point) => point.time), eventTime] : samples.map((point) => point.time);
  const start = Math.min(...times);
  const end = Math.max(...times);
  const values = samples.flatMap((point) => [point.observed, point.expected ?? null, ...(point.band ?? [])])
    .filter((value) => value !== null);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const padding = max > min ? (max - min) * 0.12 : Math.max(Math.abs(min) * 0.05, unit === "share" ? 0.01 : 1);
  const low = unit === "share" ? Math.max(0, min - padding) : min - padding;
  const high = unit === "share" ? Math.min(1, max + padding) : max + padding;
  const x = (time: number) => start === end ? WIDTH / 2 : PAD + (time - start) / (end - start) * (WIDTH - 2 * PAD);
  const y = (value: number) => (high - value) / (high - low) * HEIGHT;
  const path = (line: readonly { time: number; value: number }[]) =>
    line.map(({ time, value }, i) => `${i === 0 ? "M" : "L"}${x(time)},${y(value)}`).join(" ");
  const hasHistory = samples.filter((point) => point.observed !== null).length > 1;
  const renderDate = (time: number) => start !== end && new Date(start).toISOString().slice(0, 10) === new Date(end).toISOString().slice(0, 10)
    ? clock.format(time) : dateTime.format(time);

  return (
    <CardFrame {...card}>
      <figure className="ac-trend">
        <div className="ac-axis-chart" aria-hidden="true">
          <div className="ac-y-axis">
            {[high, low + (high - low) / 2, low].map((value) => <span key={value}>{formatValue(value, unit)}</span>)}
          </div>
          <div className="ac-plot">
            <svg viewBox={`0 0 ${WIDTH} ${HEIGHT}`} preserveAspectRatio="none">
              {[0, HEIGHT / 2, HEIGHT].map((line) => <line key={line} className="ac-grid-line" x1="0" x2={WIDTH} y1={line} y2={line} />)}
              {bands.map((band) => {
                const first = band[0];
                if (band.length === 1) {
                  return <rect
                    key={first.time}
                    className="ac-band"
                    x={x(first.time) - 10}
                    width="20"
                    y={y(first.value[1])}
                    height={Math.max(1, y(first.value[0]) - y(first.value[1]))}
                  />;
                }
                const upper = band.map(({ time, value }) => ({ time, value: value[1] }));
                const lower = band.toReversed().map(({ time, value }) => ({ time, value: value[0] }));
                return <path key={first.time} className="ac-band" d={`${path(upper)} L${path(lower).slice(1)} Z`} />;
              })}
              {expected.map((line) => line.length > 1 ? <path key={line[0].time} className="ac-expected" d={path(line)} /> : (
                <line key={line[0].time} className="ac-expected" x1={x(line[0].time) - 10} x2={x(line[0].time) + 10} y1={y(line[0].value)} y2={y(line[0].value)} />
              ))}
              {observed.map((line) => {
                const first = line[0];
                const last = line.at(-1)!;
                return line.length > 1 && (
                  <g key={first.time}>
                    <path className="ac-area" d={`${path(line)} L${x(last.time)},${HEIGHT} L${x(first.time)},${HEIGHT} Z`} />
                    <path className="ac-observed" d={path(line)} />
                  </g>
                );
              })}
              {validEvent && <line className="ac-event-line" x1={x(eventTime)} x2={x(eventTime)} y1="0" y2={HEIGHT} />}
            </svg>
            {observed.filter((line) => line.length === 1).map(([point]) => (
              <span key={point.time} className="ac-point" style={{
                "--ac-x": `${x(point.time) / WIDTH * 100}%`,
                "--ac-y": `${y(point.value) / HEIGHT * 100}%`,
              } as CSSProperties} />
            ))}
            <div className="ac-x-axis">
              <span>{renderDate(start)}{start === end && " UTC"}</span>
              {start !== end && <span>{renderDate(end)} UTC</span>}
            </div>
          </div>
        </div>
        <figcaption className="ac-trend-caption">
          <ul className="ac-trend-legend" role="list">
            <li><span className="ac-key ac-key-observed" />Observed</li>
            {expected.length > 0 && <li><span className="ac-key ac-key-expected" />Expected</li>}
            {bands.length > 0 && <li><span className="ac-key ac-key-band" />Expected range</li>}
          </ul>
          {validEvent && <EventTooltip event={validEvent} time={eventTime} />}
          {!hasHistory && <p className="ac-chart-note">One observed time bucket.</p>}
        </figcaption>
      </figure>
      <details className="ac-details">
        <summary>Chart data</summary>
        <div className="ac-table-scroll">
          <table aria-label={`${card.title} chart data`}>
            <thead><tr>
              <th scope="col">Time (UTC)</th><th scope="col">Observed</th>
              {expected.length > 0 && <th scope="col">Expected</th>}
              {bands.length > 0 && <th scope="col">Expected range</th>}
            </tr></thead>
            <tbody>
              {samples.map((point) => <tr key={point.time}>
                <th scope="row"><time dateTime={new Date(point.time).toISOString()}>{dateTime.format(point.time)}</time></th>
                <td>{formatValue(point.observed, unit)}</td>
                {expected.length > 0 && <td>{formatValue(point.expected, unit)}</td>}
                {bands.length > 0 && <td>{point.band?.map((value) => formatValue(value, unit)).join(" – ") ?? "—"}</td>}
              </tr>)}
            </tbody>
          </table>
        </div>
      </details>
    </CardFrame>
  );
}
