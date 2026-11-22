// The funnel of attention: everything watched, what was ignored, what became an anomaly, what became an incident.

import { count, hhmm } from "../lib/format";
import type { RunView } from "../lib/store";

const SHORT: Record<string, string> = {
  fact_funnel_hourly: "funnel",
  fact_payments_hourly: "payments",
  fact_orders_hourly: "orders",
  fact_ads_hourly: "ads",
  fact_ad_plan_hourly: "ad plan",
};

export function Ticker({ view }: { view: RunView }) {
  const incidents = Object.values(view.incidents);
  const open = incidents.filter((i) => i.state !== "resolved").length;
  const held = view.notes.filter((n) => n.kind === "expected" || n.kind === "data_issue").length;
  const fresh = (view.tick?.freshness ?? []).filter((f) => f.hour === view.tick?.hour);
  return (
    <div className="ticker">
      <div className="funnel" aria-label="attention funnel">
        <div className="funnel-step">
          <b>{count(view.scoredSeries)}</b>
          <span>series-hours watched</span>
        </div>
        <span className="funnel-arrow">›</span>
        <div className="funnel-step">
          <b>{count(view.wiggles)}</b>
          <span>wiggles ignored</span>
        </div>
        <span className="funnel-arrow">›</span>
        <div className="funnel-step good">
          <b>{held}</b>
          <span>didn't wake you</span>
        </div>
        <span className="funnel-arrow">›</span>
        <div className={`funnel-step${view.anomalies.length ? " alarm" : ""}`}>
          <b>{view.anomalies.length}</b>
          <span>{view.anomalies.length === 1 ? "anomaly" : "anomalies"}</span>
        </div>
        <span className="funnel-arrow">›</span>
        <div className={`funnel-step${open ? " alarm" : incidents.length ? " good" : ""}`}>
          <b>{incidents.length}</b>
          <span>
            {incidents.length === 1 ? "incident" : "incidents"}
            {incidents.length ? (open ? `, ${open} open` : ", resolved") : ""}
          </span>
        </div>
      </div>
      {fresh.length > 0 && (
        <div className="fresh" title="completeness of each source table for the scored hour">
          <span className="fresh-label">Data {hhmm(view.tick?.hour)}</span>
          {fresh.map((f) => (
            <span key={f.table} className={`chip ${f.status}`}>
              <span className="pip" />
              {SHORT[f.table] ?? f.table} {Math.round(100 * f.completeness)}%
            </span>
          ))}
        </div>
      )}
    </div>
  );
}
