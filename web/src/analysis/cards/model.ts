import { quantity } from "../../lib/format";

export type CardUnit = "count" | "eur" | "eur_per_unit" | "hours" | "pct" | "pp" | "ratio" | "share" | "value";
export type CardTone = "blue" | "violet" | "green" | "amber" | "red" | "neutral";

export interface ChartMeasure {
  value: number | null;
  unit: CardUnit;
}

export interface ChartPoint {
  at: string;
  observed: number | null;
  expected?: number | null;
  band?: readonly [number, number] | null;
}

export interface ChartEvent {
  at: string;
  label: string;
  detail: string;
}

export interface DistributionSlice {
  id: string;
  label: string;
  count: number;
  tone: CardTone;
}

export function validValue(value: number | null | undefined, unit: CardUnit): value is number {
  return typeof value === "number" && Number.isFinite(value)
    && (unit !== "share" || (value >= 0 && value <= 1));
}

export function formatValue(value: number | null | undefined, unit: CardUnit, signed = false): string {
  if (!validValue(value, unit)) return "—";
  if (unit === "pp") return `${signed && value > 0 ? "+" : ""}${value.toFixed(1)} pp`;
  if (unit === "ratio") return `${signed && value > 0 ? "+" : ""}${quantity({ value, unit: "value", receipt: null })}×`;
  return quantity({ value, unit: unit === "eur_per_unit" ? "eur" : unit, receipt: null }, signed);
}

export function timestamp(at: string): number {
  return Date.parse(/(?:Z|[+-]\d{2}:?\d{2})$/i.test(at) ? at : `${at}Z`);
}

export function chartPoints(points: readonly ChartPoint[], unit: CardUnit) {
  const byTime = new Map<number, ChartPoint & { time: number }>();
  for (const point of points) {
    const time = timestamp(point.at);
    if (!Number.isFinite(time)) continue;
    const band = point.band;
    byTime.set(time, {
      at: point.at,
      time,
      observed: validValue(point.observed, unit) ? point.observed : null,
      expected: validValue(point.expected, unit) ? point.expected : null,
      band: band && validValue(band[0], unit) && validValue(band[1], unit) && band[0] <= band[1] ? band : null,
    });
  }
  return [...byTime.values()].sort((a, b) => a.time - b.time);
}

/** Missing samples and a gap beyond the declared cadence always break a path. */
export function runs<T>(points: readonly { time: number; value: T | null }[], maxGapMs: number) {
  const groups: { time: number; value: T }[][] = [];
  let group: { time: number; value: T }[] = [];
  for (const point of points) {
    if (point.value === null) {
      group = [];
      continue;
    }
    const last = group.at(-1);
    if (!last || point.time - last.time > maxGapMs) {
      group = [];
      groups.push(group);
    }
    group.push({ time: point.time, value: point.value });
  }
  return groups;
}

export function distributionTotal(slices: readonly DistributionSlice[], total: number): number | null {
  if (!Number.isSafeInteger(total) || total <= 0) return null;
  if (new Set(slices.map((slice) => slice.id)).size !== slices.length) return null;
  if (slices.some(({ count }) => !Number.isSafeInteger(count) || count < 0)) return null;
  return slices.reduce((sum, slice) => sum + slice.count, 0) === total ? total : null;
}

const percent = new Intl.NumberFormat("en", { style: "percent", maximumFractionDigits: 1 });

export function formatPortion(portion: number): string {
  if (portion > 0 && portion < 0.0005) return "<0.1%";
  if (portion > 0.9995 && portion < 1) return ">99.9%";
  return percent.format(portion);
}
