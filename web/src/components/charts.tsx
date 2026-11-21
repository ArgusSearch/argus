// Small hand-drawn SVG charts: no chart library, every value also readable as text.

import { hhmm } from "../lib/format";

const TONES = { alarm: "#f2585d", watch: "#e3a63b", muted: "#5d6780", probe: "#5aa7ff" } as const;

export function Sparkline({
  values,
  width,
  height,
  max,
  tone = "muted",
}: {
  values: number[];
  width: number;
  height: number;
  max: number;
  tone?: keyof typeof TONES;
}) {
  if (values.length < 2) return <svg width={width} height={height} aria-hidden />;
  const step = width / Math.max(values.length - 1, 1);
  const y = (v: number) => height - 1 - (Math.min(v, max) / max) * (height - 2);
  const d = values.map((v, i) => `${i ? "L" : "M"}${(i * step).toFixed(1)},${y(v).toFixed(1)}`).join("");
  const alarmY = y(4);
  return (
    <svg width={width} height={height} aria-hidden>
      <line x1={0} x2={width} y1={alarmY} y2={alarmY} stroke="#f2585d" strokeOpacity={0.25} strokeDasharray="2 3" />
      <path d={d} fill="none" stroke={TONES[tone]} strokeWidth={1.3} strokeLinejoin="round" />
    </svg>
  );
}

export interface SeriesPoint {
  hour: string;
  value: number | null;
  expected: number | null;
}

/** Hourly series with its expectation; `mark` is the onset hour. Values are shares (0..1). */
export function TimeChart({ points, onset, height = 170 }: { points: SeriesPoint[]; onset?: string; height?: number }) {
  const width = 700;
  const pad = { l: 44, r: 12, t: 12, b: 22 };
  const vals = points.flatMap((p) => [p.value, p.expected]).filter((v): v is number => v !== null && Number.isFinite(v));
  if (!vals.length) return null;
  const lo = Math.min(...vals);
  const hi = Math.max(...vals);
  const span = hi - lo || 0.01;
  const min = lo - span * 0.1;
  const max = hi + span * 0.1;
  const x = (i: number) => pad.l + (i / Math.max(points.length - 1, 1)) * (width - pad.l - pad.r);
  const y = (v: number) => pad.t + (1 - (v - min) / (max - min)) * (height - pad.t - pad.b);
  const line = (key: "value" | "expected") =>
    points
      .map((p, i) => [p[key], i] as const)
      .filter(([v]) => v !== null)
      .map(([v, i], k) => `${k ? "L" : "M"}${x(i).toFixed(1)},${y(v as number).toFixed(1)}`)
      .join("");
  const onsetIndex = onset ? points.findIndex((p) => p.hour === onset) : -1;
  const ticks = [min + (max - min) * 0.15, (min + max) / 2, max - (max - min) * 0.15];
  return (
    <svg className="chart" viewBox={`0 0 ${width} ${height}`} role="img" aria-label="hourly series against its expectation">
      {ticks.map((t) => (
        <g key={t}>
          <line x1={pad.l} x2={width - pad.r} y1={y(t)} y2={y(t)} stroke="#1f2635" />
          <text x={pad.l - 6} y={y(t) + 3} textAnchor="end">
            {(100 * t).toFixed(0)}%
          </text>
        </g>
      ))}
      {onsetIndex >= 0 && (
        <g>
          <rect
            x={x(onsetIndex) - 4}
            y={pad.t}
            width={width - pad.r - x(onsetIndex) + 4}
            height={height - pad.t - pad.b}
            fill="rgba(242,88,93,0.07)"
          />
          <line x1={x(onsetIndex) - 4} x2={x(onsetIndex) - 4} y1={pad.t} y2={height - pad.b} stroke="#f2585d" strokeDasharray="3 3" />
          <text
            x={x(onsetIndex) - 10}
            y={pad.t + 10}
            textAnchor="end"
            style={{ fill: "#f2585d" }}
          >
            onset {hhmm(onset)}
          </text>
        </g>
      )}
      <path d={line("expected")} fill="none" stroke="#7b8498" strokeWidth={1.4} strokeDasharray="4 4" />
      <path d={line("value")} fill="none" stroke="#e7ebf3" strokeWidth={1.8} strokeLinejoin="round" />
      {points.map((p, i) =>
        i % 3 === 0 ? (
          <text key={p.hour} x={x(i)} y={height - 6} textAnchor="middle">
            {hhmm(p.hour)}
          </text>
        ) : null,
      )}
    </svg>
  );
}

export interface BarDatum {
  label: string;
  value: number; // share, may be negative
  lead?: boolean;
  rest?: boolean;
  right: React.ReactNode;
}

/** Horizontal bars around zero, for LMDI shares (shares can be negative). */
export function Bars({ data }: { data: BarDatum[] }) {
  const lo = Math.min(0, ...data.map((d) => d.value));
  const hi = Math.max(0, ...data.map((d) => d.value));
  const span = hi - lo || 1;
  const zero = ((0 - lo) / span) * 100;
  return (
    <div className="bars">
      {data.map((d) => {
        const left = ((Math.min(0, d.value) - lo) / span) * 100;
        const w = (Math.abs(d.value) / span) * 100;
        return (
          <div className="bar-row" key={d.label}>
            <span className="bar-label">{d.label}</span>
            <span className="bar-track">
              <span className="bar-zero" style={{ left: `${zero}%` }} />
              <span className={`bar-fill${d.lead ? " lead" : ""}${d.rest ? " rest" : ""}`} style={{ left: `${left}%`, width: `${w}%` }} />
            </span>
            <span className="bar-val">{d.right}</span>
          </div>
        );
      })}
    </div>
  );
}
