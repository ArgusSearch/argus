// Y6 · One line that says it all: everything here happened without a person touching anything.
// The ticker above already counts anomalies, incidents and held-back alerts, so the strip shows the rest.

import type { RunView } from "../lib/store";
import { autonomyCounts } from "./autonomy";

const SHOWN = new Set(["hours", "edges", "investigations", "human"]);

export function AutonomyStrip({ view }: { view: RunView }) {
  return (
    <div className="as" role="status" aria-label="what Argus did on its own">
      {autonomyCounts(view)
        .filter((c) => SHOWN.has(c.key))
        .map((c) => (
        <span key={c.key} className={`as-item k-${c.key}`}>
          <b>{c.value.toLocaleString("en-US")}</b> {c.label}
        </span>
      ))}
    </div>
  );
}
