// Y1 · The metric graph as a collapsible tree: business outcomes at the top, what they are made of below.

import { useEffect, useMemo, useState } from "react";
import type { RunView } from "../lib/store";
import type { Graph } from "../lib/types";
import { metricStatus } from "./model";
import { buildTree, countMetrics, openPathTo, statusOrNull, VIA_LABEL, type TreeRow } from "./tree";

interface Props {
  graph: Graph | null;
  view: RunView;
  onSelectNode: (id: string) => void;
}

function Chevron({ open }: { open: boolean }) {
  return (
    <svg className={`tv-chev${open ? " open" : ""}`} width="10" height="10" viewBox="0 0 10 10" aria-hidden>
      <path d="M3.2 1.8 6.6 5 3.2 8.2" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

export function TreeView({ graph, view, onSelectNode }: Props) {
  const tree = useMemo(() => (graph ? buildTree(graph) : null), [graph]);
  const [open, setOpen] = useState<Set<string>>(() => new Set());
  const [query, setQuery] = useState("");
  const labels = useMemo(() => new Map((graph?.nodes ?? []).map((n) => [n.id, n])), [graph]);
  const logLabels = useMemo(() => new Map((graph?.logs ?? []).map((l) => [l.id, l.label])), [graph]);
  const focusNodes = view.focus?.nodes ?? [];
  const focusKey = focusNodes.join(",");

  // first paint: the top two levels are open
  useEffect(() => {
    if (!tree) return;
    setOpen(new Set([...tree.roots, ...tree.unattached].map((r) => r.key)));
  }, [tree]);

  // the running investigation opens the tree down to the metrics it is checking
  useEffect(() => {
    if (!tree || !focusKey) return;
    const path = openPathTo(tree, focusKey.split(","));
    if (!path.size) return;
    setOpen((prev) => (([...path].every((k) => prev.has(k)) ? prev : new Set([...prev, ...path]))));
  }, [tree, focusKey]);

  if (!graph || !tree) return <div className="vw-empty">Loading the metric graph…</div>;

  const q = query.trim().toLowerCase();
  const matches = (row: TreeRow): boolean => {
    if (!q) return true;
    const label = row.kind === "metric" ? (labels.get(row.id)?.label ?? row.id) : row.kind === "log" ? (logLabels.get(row.id) ?? row.id) : row.id;
    return row.id.toLowerCase().includes(q) || label.toLowerCase().includes(q) || row.children.some(matches);
  };

  const toggle = (key: string) =>
    setOpen((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });

  const setAll = (value: boolean) => {
    if (!value) return setOpen(new Set());
    const keys: string[] = [];
    const walk = (r: TreeRow) => {
      if (r.children.length) keys.push(r.key);
      r.children.forEach(walk);
    };
    [...tree.roots, ...tree.unattached].forEach(walk);
    setOpen(new Set(keys));
  };

  const renderRow = (row: TreeRow) => {
    if (!matches(row)) return null;
    const expanded = q ? true : open.has(row.key);
    const status = statusOrNull(row.edge, view.edges);
    const hasKids = row.children.length > 0;
    const indent = { paddingLeft: 14 + row.depth * 20 };

    if (row.kind !== "metric") {
      const isLog = row.kind === "log";
      const focused = isLog && (view.focus?.logs ?? []).includes(row.id);
      return (
        <li key={row.key} role="treeitem" aria-level={row.depth + 1} className={`tv-row leaf k-${row.kind}${focused ? " focus" : ""}`} style={indent}>
          <span className="tv-chev-space" />
          <span className={`tv-via v-${row.via}`}>{row.via ? VIA_LABEL[row.via] : ""}</span>
          <span className="tv-name">{isLog ? (logLabels.get(row.id) ?? row.id) : `by ${row.id.replace(/_/g, " ")}`}</span>
          <span className="tv-id mono">{isLog ? row.id : row.edge?.id}</span>
          <span className="tv-fill" />
          {status && <span className={`tv-badge ${status}`}>{status}</span>}
        </li>
      );
    }

    const node = labels.get(row.id);
    const st = metricStatus(view, row.id);
    const checking = st.state === "checking";
    return (
      <li key={row.key} role="treeitem" aria-level={row.depth + 1} aria-expanded={hasKids ? expanded : undefined} className="tv-item">
        <div className={`tv-row metric s-${st.state}${row.ref ? " ref" : ""}${checking ? " focus" : ""}`} style={indent}>
          {hasKids ? (
            <button className="tv-toggle" onClick={() => toggle(row.key)} aria-label={expanded ? "Collapse" : "Expand"}>
              <Chevron open={expanded} />
            </button>
          ) : (
            <span className="tv-chev-space" />
          )}
          {row.via && <span className={`tv-via v-${row.via}`}>{VIA_LABEL[row.via]}</span>}
          <button className="tv-name tv-link" onClick={() => onSelectNode(row.id)} title={node?.description ?? row.id}>
            {node?.north_star && <span className="tv-star" aria-label="north star">★</span>}
            {node?.label ?? row.id}
          </button>
          <span className="tv-id mono">{row.id}</span>
          {node?.kind === "ratio" && <span className="tv-kind">rate</span>}
          {row.ref && (
            <span className="tv-ref" title="This metric is expanded at its first place in the tree">
              ↗ also under {tree.home[row.id]?.split("/").slice(-2, -1)[0]?.replace(/_/g, " ") ?? "another metric"}
            </span>
          )}
          <span className="tv-fill" />
          <span className={`tv-state s-${st.state}`} title={st.z === null ? "not scored this hour" : `|z| ${st.z.toFixed(1)} this hour`}>
            <i />
            {st.label}
            {st.z !== null && <b className="mono">{st.z.toFixed(1)}</b>}
          </span>
          {status ? <span className={`tv-badge ${status}`}>{status}</span> : <span className="tv-badge none">{row.via === "ratio" ? "RATIO" : ""}</span>}
        </div>
        {hasKids && expanded && <ul role="group">{row.children.map(renderRow)}</ul>}
      </li>
    );
  };

  return (
    <section className="vw tv" aria-label="metric tree">
      <div className="vw-bar">
        <div>
          <h2 className="vw-title">Metric tree</h2>
          <p className="vw-sub">
            Business outcomes at the top, what they are made of below. Each line hangs on a typed edge with a live test;{" "}
            <b>{countMetrics(tree.roots)}</b> of {graph.nodes.length} metrics sit under a north star.
          </p>
        </div>
        <span className="tv-fill" />
        <input className="vw-search" placeholder="Find a metric" value={query} onChange={(e) => setQuery(e.target.value)} aria-label="Find a metric" />
        <button className="btn" onClick={() => setAll(true)}>
          Expand all
        </button>
        <button className="btn" onClick={() => setAll(false)}>
          Collapse
        </button>
      </div>
      <div className="vw-scroll">
        <ul className="tv-list" role="tree" aria-label="metrics under the north stars">
          {tree.roots.map(renderRow)}
        </ul>
        {tree.unattached.length > 0 && (
          <>
            <div className="tv-section">
              Not under a north star <span className="muted">· metrics that no outcome is built from yet</span>
            </div>
            <ul className="tv-list" role="tree" aria-label="unattached metrics">
              {tree.unattached.map(renderRow)}
            </ul>
          </>
        )}
        <div className="tv-legend">
          <span>
            <span className="tv-via v-formula">formula</span> exact arithmetic, split with LMDI
          </span>
          <span>
            <span className="tv-via v-ratio">ratio of</span> numerator and denominator
          </span>
          <span>
            <span className="tv-via v-breakdown">breakdown</span> children sum to the parent
          </span>
          <span>
            <span className="tv-via v-cause">possible cause</span> lagged and tested, never assumed
          </span>
          <span>
            <span className="tv-via v-evidence">evidence</span> a log of changes that can explain it
          </span>
        </div>
      </div>
    </section>
  );
}
