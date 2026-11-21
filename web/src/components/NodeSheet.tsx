// One metric: what it is, its SQL, and every edge that touches it with the edge's live test.

import { useEffect } from "react";
import { humanize } from "../lib/format";
import { ALARM_Z, type RunView } from "../lib/store";
import type { EdgeTestResult, Graph, GraphEdge } from "../lib/types";
import { Sparkline } from "./charts";
import { ReceiptChips, formatSql } from "./Receipts";

function testLine(r: EdgeTestResult | null | undefined, kind: string): string {
  if (!r && kind === "evidence") return "tested inside every investigation: onset alignment and scope";
  if (!r && kind === "cause") return "lagged-correlation test pending: weight follows the status";
  if (!r) return "not tested yet";
  if (r.median_rel !== null && r.p95_rel !== null) {
    return `residual ${(100 * r.median_rel).toFixed(2)}% median, ${(100 * r.p95_rel).toFixed(2)}% p95 over ${r.hours} h`;
  }
  if (r.max_rel_err !== null) return `parts sum to the whole within ${(100 * r.max_rel_err).toFixed(3)}% over ${r.hours} h`;
  return r.note || "checked per investigation";
}

const KIND_TEXT: Record<string, string> = {
  formula: "formula: exact split",
  breakdown: "breakdown: where",
  cause: "cause: possible next hop",
  evidence: "evidence: first-cause candidates",
};

export function NodeSheet({ id, graph, view, onClose }: { id: string; graph: Graph; view: RunView; onClose: () => void }) {
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const node = graph.nodes.find((n) => n.id === id);
  const log = graph.logs.find((l) => l.id === id);
  const touching = graph.edges.filter((e) => e.target === id || e.sources.includes(id));
  const history = view.zHistory[id] ?? [];
  const z = view.tick?.max_abs_z[id];
  const status = (e: GraphEdge) => view.edges[e.id]?.status ?? e.status;
  const result = (e: GraphEdge) => view.edges[e.id]?.result ?? e.last_test;

  return (
    <>
      <div className="scrim" onClick={onClose} />
      <section className="sheet narrow" role="dialog" aria-label={`Metric ${id}`}>
        <div className="sheet-head">
          <div className="sheet-top">
            <span className="mono">{id}</span>
            {node?.north_star && <span className="pill state-explained">north star</span>}
            <span className="pill">{node ? (node.kind === "ratio" ? "rate" : node.kind) : "log"}</span>
            <span className="spacer" />
            <button className="icon-btn" onClick={onClose} aria-label="Close">
              ✕
            </button>
          </div>
          <h2 className="sheet-title">{node?.label ?? log?.label ?? id}</h2>
          <p className="muted" style={{ margin: "6px 0 0" }}>
            {node?.description ?? log?.description}
          </p>
        </div>
        <div className="sheet-body">
          {node && (
            <div className="sec">
              <h3>This hour</h3>
              <div className="node-now">
                <div>
                  <b className={z !== undefined && z >= ALARM_Z ? "alarm" : ""}>{z !== undefined ? z.toFixed(1) : "–"}</b>
                  <span>|z| against the same hour of the last 4 weeks · alarm line {ALARM_Z}</span>
                </div>
                <Sparkline values={history} width={300} height={40} max={Math.max(ALARM_Z + 1, ...history)} tone="probe" />
              </div>
            </div>
          )}
          {node?.sql && (
            <div className="sec">
              <h3>Definition (C2 SQL)</h3>
              <pre className="sql">{formatSql(node.sql)}</pre>
              {node.dims.length > 0 && (
                <p className="muted" style={{ fontSize: 12 }}>
                  Breaks down by {node.dims.map(humanize).join(", ")}.
                </p>
              )}
            </div>
          )}
          <div className="sec">
            <h3>Edges · each one is a contract with a test</h3>
            <div className="edge-list" style={{ maxHeight: "none" }}>
              {touching.map((e) => (
                <div key={e.id} className="edge-row">
                  <span className="mono" title={e.expr ?? e.id}>
                    {e.kind === "breakdown"
                      ? `${e.target} by ${e.dim}`
                      : e.kind === "formula"
                        ? `${e.target} = ${e.expr}`
                        : `${e.sources.join(", ")} → ${e.target}`}
                  </span>
                  <span className="transition">
                    <span className={`st ${status(e)}`}>{status(e)}</span>
                  </span>
                  <span className="edge-test">
                    {KIND_TEXT[e.kind]} · {testLine(result(e), e.kind)} <ReceiptChips ids={result(e)?.receipts ?? []} max={2} />
                  </span>
                </div>
              ))}
              {!touching.length && <div className="muted">No edges yet.</div>}
            </div>
          </div>
        </div>
      </section>
    </>
  );
}
