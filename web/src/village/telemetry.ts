import type { ArgusEvent, TickPayload } from "../lib/types";

export interface WatchSeries {
  label: string;
  values: (number | null)[];
}

export type MarketVerdict = "market" | "us" | "inconclusive";

/** The room screens use only observations at or before the current simulation hour. */
export function watchSeries(events: readonly ArgusEvent[], asOf: string, labels: Record<string, string>): WatchSeries[] {
  const rows: TickPayload["max_abs_z"][] = [];
  for (let i = events.length - 1; i >= 0 && rows.length < 18; i--) {
    const event = events[i];
    if (event.type === "tick" && event.sim_ts <= asOf) rows.push(event.payload.max_abs_z);
  }
  rows.reverse();
  const keys = Object.keys(rows.at(-1) ?? {}).slice(0, 6);
  return keys.map((key) => ({ label: labels[key] ?? key, values: rows.map((row) => row[key] ?? null) }));
}

export function marketVerdict(events: readonly ArgusEvent[], asOf: string): MarketVerdict | null {
  for (let i = events.length - 1; i >= 0; i--) {
    const event = events[i];
    if (event.type !== "investigation_step" || event.sim_ts > asOf) continue;
    const control = event.payload.step.data?.market_control;
    if (!control || typeof control !== "object" || !("verdict" in control)) continue;
    if (control.verdict === "market" || control.verdict === "us") return control.verdict;
    return "inconclusive";
  }
  return null;
}
