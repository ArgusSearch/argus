// The graph extension on top of a graph panel: the newest placement as a card, a chip per placement to switch
// between them, an "Add the ad metric pack" control, and a highlight on the placed nodes wherever the page draws
// them (React Flow nodes carry `data-id`, tree rows `data-node`), the newest one arriving with a pulse.

import { useEffect, useState } from "react";
import { NewMetricCard } from "./NewMetricCard";
import { labelOf, nextOfPack, placedNodes, VERDICT_TONE } from "./model";
import type { GraphExtension } from "./useGraphExtension";

const esc = (id: string) => id.replace(/[^a-z0-9_]/g, "");

/** Global highlight rules for the placed nodes; the newest gets the arrival animation. */
export function placedNodeStyles(ids: string[]): string {
  if (!ids.length) return "";
  const all = ids.map(esc);
  const newest = all[all.length - 1];
  const node = (id: string) => `.react-flow__node[data-id="${id}"] .mnode`;
  const row = (id: string) => `[data-node="${id}"]`;
  return [
    `${all.map(node).join(", ")} { box-shadow: 0 0 0 1.5px var(--gx-placed, #3fbf8f), 0 0 16px rgba(63, 191, 143, 0.28); }`,
    `${all.map(row).join(", ")} { box-shadow: inset 2px 0 0 var(--gx-placed, #3fbf8f); }`,
    `${node(newest)} { animation: gx-arrive 1.6s cubic-bezier(0.2, 0.9, 0.3, 1.2) both; }`,
    `${row(newest)} { animation: gx-row-arrive 2.4s ease-out both; }`,
  ].join("\n");
}

export function GraphExtensionLayer({ ext }: { ext: GraphExtension }) {
  const { state, current } = ext;
  const [hidden, setHidden] = useState(false);
  const count = state?.placements.length ?? 0;
  useEffect(() => setHidden(false), [count]); // a new placement always shows its card
  if (!state) return null;
  const next = nextOfPack(state);
  const left = state.recorded.length - state.placements.filter((p) => state.recorded.some((m) => m.name === p.metric.name)).length;
  return (
    <div className="gx-layer">
      <style>{placedNodeStyles(placedNodes(state.placements))}</style>
      {current && !hidden && <NewMetricCard key={current.metric.name} placement={current} onClose={() => setHidden(true)} />}
      <div className="gx-bar" role="toolbar" aria-label="new metrics">
        {state.placements.map((p) => (
          <button
            key={p.metric.name}
            className={`gx-pill ${VERDICT_TONE[p.placed_as]}${current?.metric.name === p.metric.name && !hidden ? " on" : ""}`}
            onClick={() => {
              ext.select(p.metric.name);
              setHidden(false);
            }}
            title={`${p.placed_as}: ${p.summary}`}
          >
            {labelOf(p.metric.name)}
          </button>
        ))}
        {next && (
          <button className="gx-add" onClick={ext.placePack} disabled={ext.busy}>
            {ext.busy ? "Placing…" : `Add the ad metric pack (${left})`}
          </button>
        )}
        {ext.error && <span className="gx-error">{ext.error}</span>}
      </div>
    </div>
  );
}
