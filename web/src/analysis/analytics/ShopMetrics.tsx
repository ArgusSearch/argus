import { health } from "../../fx/workspace/health";
import type { RunView } from "../../lib/store";
import type { Graph } from "../../lib/types";
import { dateTime, time } from "./model";

export function ShopMetrics({ view, graph }: { view: RunView; graph: Graph | null }) {
  const { checks } = health(view, graph);
  const at = time(view.simTs);
  return (
    <section className="an-shop" aria-label="Shop Metrics">
      <div className="an-shop-head">
        <h2>Shop Metrics</h2>
        <p>Whole shop{at !== null && ` · ${dateTime(at)}`}</p>
      </div>
      <ul>
        {checks.map(({ key, label, passed, total, share, tone, detail }) => {
          const available = total > 0 && at !== null;
          return (
            <li className={`fx-card an-card t-${available ? tone : "muted"}`} key={key}>
              <svg className="an-ring" viewBox="0 0 44 44" aria-hidden="true">
                <circle className="an-ring-track" cx="22" cy="22" r="18" />
                {available && share > 0 && (
                  <circle className="an-ring-value" cx="22" cy="22" r="18" pathLength="100"
                    strokeDasharray={`${100 * share} 100`} transform="rotate(-90 22 22)" />
                )}
              </svg>
              <div>
                <h3>{label}</h3>
                <strong title={available ? detail : undefined}>{available ? `${passed} / ${total}` : "—"}</strong>
                {!available && <p>{detail}</p>}
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}
