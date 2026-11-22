import type { Direction, Graph, Quantity, Segment } from "./types";

const DAY = new Intl.DateTimeFormat("en-GB", { weekday: "short", day: "2-digit", month: "short", timeZone: "UTC" });

/** Simulated timestamps are naive UTC ("2026-11-21T18:00:00"); never shift them into the viewer's zone. */
function parse(ts: string): Date {
  return new Date(/(?:Z|[+-]\d\d:\d\d)$/i.test(ts) ? ts : `${ts}Z`);
}

export function timestamp(ts: string | null): number {
  return ts ? parse(ts).valueOf() : NaN;
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

/** Translate identifiers embedded in monitoring prose. Keep the original keys for links and lookups. */
export function monitoringText(text: string): string {
  return text.replace(/\ban_\d+\b/gi, "the metric alert").replace(/\br\d+\b/g, "the evidence query");
}

/**
 * What an incident's EUR figure counts, from the node it is measured on. Orders and payments that go
 * missing cost GMV; a metric that is money itself, or a ratio over money (pacing_ratio = ad_spend /
 * planned_spend), moves that money instead: a pacer overburn is extra ad spend, not lost GMV.
 */
export function impactNoun(nodeId: string, direction: Direction, graph: Graph | null | undefined): string {
  const node = graph?.nodes.find((n) => n.id === nodeId);
  const moneyId = node?.unit === "eur" ? node.id : node?.kind === "ratio" ? node.numerator : null;
  const money = moneyId && moneyId !== "gmv" ? graph?.nodes.find((n) => n.id === moneyId && n.unit === "eur") : undefined;
  if (!money) return direction === "down" ? "GMV lost" : "extra GMV";
  const label = money.label.charAt(0).toLowerCase() + money.label.slice(1);
  return direction === "up" ? `extra ${label}` : `${label} short`;
}

const VERDICTS = new Set(["SUPPORTED_CAUSE", "HYPOTHESIS", "EXPECTED", "DATA_ISSUE", "UNEXPLAINED"]);

/** One way to write a verdict everywhere on the page: SUPPORTED_CAUSE -> "SUPPORTED CAUSE". Other text passes through. */
export function verdictLabel(text: string): string {
  return VERDICTS.has(text) ? text.replaceAll("_", " ") : text;
}
