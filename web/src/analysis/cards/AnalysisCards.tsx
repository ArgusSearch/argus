import { useId, type CSSProperties, type ReactNode } from "react";
import { count } from "../../lib/format";
import {
  distributionTotal, formatPortion, formatValue, validValue,
  type CardTone, type CardUnit, type ChartMeasure, type DistributionSlice,
} from "./model";
import "./cards.css";

export interface CardProps {
  title: string;
  context?: string;
  footer?: ReactNode;
  empty?: string;
}

export interface MetricChange extends ChartMeasure {
  /** Name the comparison, for example "vs expected" or "vs previous week". */
  basis: string;
  tone?: CardTone;
}

export function CardFrame({ title, context, footer, children }: CardProps & { children: ReactNode }) {
  const id = useId();
  return (
    <section className="ac-card" aria-labelledby={id}>
      <header className="ac-header">
        <h2 id={id}>{title}</h2>
        {context && <p>{context}</p>}
      </header>
      {children}
      {footer && <footer className="ac-footer">{footer}</footer>}
    </section>
  );
}

export function CardEmpty({ children = "No observations in this scope." }: { children?: ReactNode }) {
  return <p className="ac-empty">{children}</p>;
}

export function CardValue({ value, unit, change }: ChartMeasure & { change?: MetricChange }) {
  return (
    <div className="ac-reading">
      <strong className="ac-value">{formatValue(value, unit)}</strong>
      {change && validValue(change.value, change.unit) && (
        <span className="ac-change" data-tone={change.tone ?? "neutral"}>
          {formatValue(change.value, change.unit, true)} {change.basis}
        </span>
      )}
    </div>
  );
}

export interface BarValue {
  id: string;
  label: string;
  value: number | null;
  /** Highlights a distinct kind of observation. Name it in hatchLabel. */
  hatched?: boolean;
}

export interface MetricBarsCardProps extends CardProps {
  metric?: ChartMeasure;
  change?: MetricChange;
  unit: CardUnit;
  bars: readonly BarValue[];
  hatchLabel?: string;
}

export function MetricBarsCard({ metric, change, unit, bars, hatchLabel, ...card }: MetricBarsCardProps) {
  const values = bars.map((bar) => bar.value).filter((value) => validValue(value, unit));
  const low = Math.min(0, ...values);
  const high = Math.max(0, ...values);
  const span = high - low || 1;
  const position = (value: number) => (high - value) / span * 100;

  return (
    <CardFrame {...card}>
      {metric && validValue(metric.value, metric.unit) && <CardValue {...metric} change={change} />}
      {values.length ? (
        <>
          <ul role="list" className="ac-bars" style={{ "--ac-zero": `${position(0)}%` } as CSSProperties}>
            {bars.map((bar) => {
              const value = validValue(bar.value, unit) ? bar.value : null;
              return (
                <li key={bar.id} className="ac-bar">
                  <span className="ac-bar-pill">{value === null ? "No value" : formatValue(value, unit, true)}</span>
                  <span className="ac-bar-track" aria-hidden="true">
                    {value !== null && <span
                      className="ac-bar-fill"
                      data-hatched={bar.hatched || undefined}
                      data-zero={value === 0 || undefined}
                      style={{ top: `${position(Math.max(0, value))}%`, height: `${Math.abs(value) / span * 100}%` }}
                    />}
                  </span>
                  <span className="ac-bar-label">{bar.label}</span>
                  {bar.hatched && hatchLabel && <span className="ac-sr-only">, {hatchLabel}</span>}
                </li>
              );
            })}
          </ul>
          {hatchLabel && bars.some((bar) => bar.hatched) && (
            <p className="ac-legend"><span className="ac-key ac-key-hatch" />{hatchLabel}</p>
          )}
        </>
      ) : <CardEmpty>{card.empty}</CardEmpty>}
    </CardFrame>
  );
}

const TICKS = 44;

export interface TickRingCardProps extends CardProps {
  share: number | null;
  benchmark?: { share: number; label: string };
}

export function TickRingCard({ share, benchmark, ...card }: TickRingCardProps) {
  const observed = validValue(share, "share") ? share : null;
  const validBenchmark = benchmark && validValue(benchmark.share, "share") ? benchmark : null;
  return (
    <CardFrame {...card}>
      {observed === null ? <CardEmpty>{card.empty}</CardEmpty> : (
        <>
          <div className="ac-ring">
            <svg viewBox="0 0 116 116" aria-hidden="true">
              {Array.from({ length: TICKS }, (_, index) => (
                <line
                  key={index}
                  className="ac-tick"
                  data-filled={index < Math.floor(observed * TICKS) || undefined}
                  x1="58" x2="58" y1="7" y2="16"
                  transform={`rotate(${index * 360 / TICKS} 58 58)`}
                />
              ))}
            </svg>
            <div className="ac-ring-center">
              <strong className="ac-value">{formatPortion(observed)}</strong>
              <span>Observed</span>
            </div>
          </div>
          {validBenchmark && <p className="ac-legend">{validBenchmark.label} {formatPortion(validBenchmark.share)}</p>}
        </>
      )}
    </CardFrame>
  );
}

export interface DistributionCardProps extends CardProps {
  /** Mutually exclusive categories from one population with an independent total. */
  slices: readonly DistributionSlice[];
  total: number | null;
  totalLabel: string;
}

export function DistributionCard({ slices, total, totalLabel, ...card }: DistributionCardProps) {
  const denominator = total === null ? null : distributionTotal(slices, total);
  let start = 0;
  const arcs = denominator === null ? [] : slices.filter((slice) => slice.count > 0).map((slice) => {
    const portion = slice.count / denominator;
    const arc = { ...slice, portion, start };
    start += portion;
    return arc;
  });
  const gap = arcs.length > 1 ? 1.8 : 0;
  return (
    <CardFrame {...card}>
      {denominator === null ? <CardEmpty>{card.empty ?? "No complete distribution for this scope."}</CardEmpty> : (
        <>
          <div className="ac-ring">
            <svg viewBox="0 0 116 116" aria-hidden="true">
              <circle className="ac-ring-base" cx="58" cy="58" r="47" />
              {arcs.map(({ id, tone, portion, start }) => {
                const size = portion * 100;
                const separation = Math.min(gap, size / 2);
                return <circle
                  key={id}
                  className="ac-arc"
                  data-tone={tone}
                  cx="58" cy="58" r="47" pathLength="100"
                  strokeDasharray={`${size - separation} ${100 - size + separation}`}
                  strokeDashoffset={-start * 100 - separation / 2}
                  transform="rotate(-90 58 58)"
                />;
              })}
            </svg>
            <div className="ac-ring-center">
              <strong className="ac-value">{count(denominator)}</strong>
              <span>{totalLabel}</span>
            </div>
          </div>
          <ul role="list" className="ac-slices">
            {slices.map((slice) => (
              <li key={slice.id}>
                <span className="ac-slice-label"><span className="ac-key" data-tone={slice.tone} />{slice.label}</span>
                <span className="ac-slice-value">{count(slice.count)} <strong>{formatPortion(slice.count / denominator)}</strong></span>
              </li>
            ))}
          </ul>
        </>
      )}
    </CardFrame>
  );
}
