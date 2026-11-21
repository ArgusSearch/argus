import type { Quantity, Segment } from "./types";

const DAY = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" });

/** Simulated timestamps are naive UTC ("2026-11-21T18:00:00"); never shift them into the viewer's zone. */
function parse(ts: string): Date {
  return new Date(ts.endsWith("Z") ? ts : `${ts}Z`);
}

export function hhmm(ts: string | null | undefined): string {
  if (!ts) return "--:--";
  const d = parse(ts);
  return `${String(d.getUTCHours()).padStart(2, "0")}:${String(d.getUTCMinutes()).padStart(2, "0")}`;
}

export function dayLabel(ts: string | null | undefined): string {
  return ts ? DAY.format(parse(ts)) : "";
}

export function eur(value: number, signed = false): string {
  const sign = value < 0 ? "-" : signed && value > 0 ? "+" : "";
  const abs = Math.abs(value);
  const text = abs >= 1000 ? abs.toLocaleString("en-US", { maximumFractionDigits: 0 }) : abs.toFixed(abs >= 100 ? 0 : 2);
  return `${sign}€${text}`;
}

export function pct(value: number, digits = 1): string {
  return `${value > 0 ? "+" : ""}${value.toFixed(digits)}%`;
}

export function share(value: number, digits = 0): string {
  return `${(100 * value).toFixed(digits)}%`;
}

export function count(value: number): string {
  return Math.round(value).toLocaleString("en-US");
}

export function quantity(q: Quantity, signed = false): string {
  switch (q.unit) {
    case "eur":
      return eur(q.value, signed);
    case "pct":
      return pct(q.value);
    case "share":
      return `${(100 * q.value).toFixed(1)}%`;
    case "count":
      return `${signed && q.value > 0 ? "+" : ""}${count(q.value)}`;
    case "z":
      return `z ${q.value > 0 ? "+" : ""}${q.value.toFixed(1)}`;
    case "hours":
      return `${q.value} h`;
    default:
      return q.value.toLocaleString("en-US", { maximumFractionDigits: 3 });
  }
}

const DIM_ORDER = ["country", "platform", "provider", "channel", "category", "advertiser_id"];

export function segmentEntries(segment: Segment): [string, string][] {
  return Object.entries(segment).sort(([a], [b]) => DIM_ORDER.indexOf(a) - DIM_ORDER.indexOf(b));
}

export function segmentLabel(segment: Segment): string {
  const entries = segmentEntries(segment);
  return entries.length ? entries.map(([, v]) => v).join(" · ") : "all traffic";
}

export function humanize(id: string): string {
  return id.replace(/_/g, " ");
}
