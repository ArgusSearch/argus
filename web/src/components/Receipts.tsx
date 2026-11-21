// Receipts: every number links to the query that produced it; the drawer re-runs it and compares hashes.

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { agentApi, type AgentReceipt, type ReceiptLink } from "../lib/agent";
import { demoRunId } from "../lib/agentDemo";
import { api } from "../lib/api";
import { hhmm, dayLabel, quantity } from "../lib/format";
import type { Quantity, RerunResult } from "../lib/types";

/** A C4 receipt id of the run on screen, or an agent receipt qualified by its run and world revision. */
export type ReceiptTarget = string | ReceiptLink;

const ReceiptContext = createContext<(target: ReceiptTarget) => void>(() => {});

export function useOpenReceipt(): (target: ReceiptTarget) => void {
  return useContext(ReceiptContext);
}

export function ReceiptProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<ReceiptTarget | null>(null);
  const openReceipt = useCallback((target: ReceiptTarget) => setOpen(target), []);
  const close = useCallback(() => setOpen(null), []);
  return (
    <ReceiptContext.Provider value={openReceipt}>
      {children}
      {open && <ReceiptDrawer key={typeof open === "string" ? open : linkKey(open)} target={open} onClose={close} />}
    </ReceiptContext.Provider>
  );
}

export function ReceiptChips({ ids, max = 4 }: { ids: string[]; max?: number }) {
  const openReceipt = useOpenReceipt();
  if (!ids.length) return null;
  const shown = ids.slice(0, max);
  return (
    <span className="receipts">
      {shown.map((id) => (
        <button
          key={id}
          className="rcpt"
          title="Open the query behind this number"
          onClick={(e) => {
            e.stopPropagation();
            openReceipt(id);
          }}
        >
          {id}
        </button>
      ))}
      {ids.length > max && <span className="muted mono">+{ids.length - max}</span>}
    </span>
  );
}

const linkKey = (l: ReceiptLink) => `${l.run_id}/${l.world_revision}/${l.receipt_id}`;

/** Receipts of an agent run (qualified links): the same drawer, reading GET /agent/receipts/... */
export function AgentReceiptChips({ links, max = 4 }: { links: ReceiptLink[]; max?: number }) {
  const openReceipt = useOpenReceipt();
  if (!links.length) return null;
  const shown = links.slice(0, max);
  return (
    <span className="receipts">
      {shown.map((l) => (
        <button
          key={linkKey(l)}
          className="rcpt"
          title={`Open the query behind this number (${l.run_id}, ${l.world_revision})`}
          onClick={(e) => {
            e.stopPropagation();
            openReceipt(l);
          }}
        >
          {l.receipt_id}
        </button>
      ))}
      {links.length > max && <span className="muted mono">+{links.length - max}</span>}
    </span>
  );
}

/** A number with its receipt: click to see the SQL and re-run it. */
export function Num({ q, signed = false, text }: { q: Quantity; signed?: boolean; text?: string }) {
  const openReceipt = useOpenReceipt();
  const label = text ?? quantity(q, signed);
  if (!q.receipt) {
    return (
      <span className="num plain" title="derived from other numbers">
        {label}
      </span>
    );
  }
  const id = q.receipt;
  return (
    <button
      className="num"
      title={`receipt ${id}: click for SQL and re-run`}
      onClick={(e) => {
        e.stopPropagation();
        openReceipt(id);
      }}
    >
      {label}
    </button>
  );
}

const KEYWORDS =
  /\b(SELECT|FROM|WHERE|GROUP BY|ORDER BY|JOIN|USING|WITH|AS|AND|OR|NOT|IN|BETWEEN|SUM|CASE|WHEN|THEN|END|UNION ALL|CROSS JOIN|TIMESTAMP|NULLIF|FILTER|ALL)\b/g;

/** Break long one-line SQL before its main clauses so it reads top to bottom. */
export function formatSql(sql: string): string {
  return sql
    .replace(/\s+(FROM|WHERE|GROUP BY|ORDER BY|UNION ALL|JOIN|CROSS JOIN)\s+/g, "\n$1 ")
    .replace(/\),\s*(t\d+ AS \()/g, "),\n$1")
    .replace(/\s+(OR ts BETWEEN)/g, "\n   $1");
}

function highlight(sql: string): ReactNode[] {
  const out: ReactNode[] = [];
  const pattern = /('[^']*')|(\b\d+(?:\.\d+)?\b)|([A-Za-z_]+(?: (?:BY|ALL|JOIN))?)|(\s+|[^\sA-Za-z_'\d]+)/g;
  let m: RegExpExecArray | null;
  let i = 0;
  while ((m = pattern.exec(sql))) {
    const [token, str, num, word] = m;
    if (str) out.push(<span key={i++} className="str">{str}</span>);
    else if (num) out.push(<span key={i++} className="num">{num}</span>);
    else if (word && new RegExp(`^(${KEYWORDS.source})$`).test(word)) out.push(<span key={i++} className="kw">{word}</span>);
    else out.push(token);
  }
  return out;
}

function ReceiptDrawer({ target, onClose }: { target: ReceiptTarget; onClose: () => void }) {
  const agent = typeof target === "string" ? null : target;
  const id = typeof target === "string" ? target : target.receipt_id;
  const [receipt, setReceipt] = useState<AgentReceipt | null>(null);
  // during the agent presentation a plain receipt id is one the presentation revealed: its own route
  const demo = typeof target === "string" && demoRunId() !== null;
  const [error, setError] = useState<string | null>(null);
  const [rerun, setRerun] = useState<RerunResult | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let live = true;
    setReceipt(null);
    setRerun(null);
    setError(null);
    (agent ? agentApi.receipt(agent) : demo ? agentApi.demoReceipt(id) : (api.receipt(id) as Promise<AgentReceipt>)).then(
      (r) => live && setReceipt(r),
      (e: Error) => live && setError(e.message),
    );
    return () => {
      live = false;
    };
  }, [id, agent, demo]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const run = async () => {
    setRunning(true);
    setError(null);
    try {
      setRerun(await api.rerun(id));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setRunning(false);
    }
  };

  return (
    <>
      <div className="scrim top" onClick={onClose} />
      <div className="modal" role="dialog" aria-label={`Receipt ${id}`}>
        <div className="modal-head">
          <div style={{ flex: 1 }}>
            <h2>
              Receipt <span className="mono">{id}</span>
            </h2>
            <p>{receipt?.purpose || "The query behind this number, pinned to the data as it was at as_of."}</p>
            {agent && (
              <p className="mono muted">
                agent run {agent.run_id} · world {agent.world_revision}
              </p>
            )}
          </div>
          <button className="icon-btn" onClick={onClose} aria-label="Close">
            ✕
          </button>
        </div>
        <div className="modal-body">
          {receipt ? (
            <>
              <div className="facts">
                <div>
                  <label>as_of (pinned)</label>
                  <span className="mono">
                    {dayLabel(receipt.as_of)} {hhmm(receipt.as_of)}
                  </span>
                </div>
                <div>
                  <label>rows</label>
                  <span className="mono">{receipt.rows}</span>
                </div>
                <div>
                  <label>ran in</label>
                  <span className="mono">{receipt.ms.toFixed(1)} ms</span>
                </div>
                <div>
                  <label>result hash</label>
                  <span className="mono" title={receipt.result_hash}>
                    {receipt.result_hash.replace("sha256:", "")}
                  </span>
                </div>
              </div>
              <pre className="sql">{highlight(formatSql(receipt.sql))}</pre>
              {receipt.columns && receipt.columns.length > 0 && receipt.captured_rows && receipt.captured_rows.length > 0 && (
                <table className="captured">
                  <thead>
                    <tr>
                      {receipt.columns.map((c) => (
                        <th key={c}>{c}</th>
                      ))}
                    </tr>
                  </thead>
                  <tbody>
                    {receipt.captured_rows.slice(0, 8).map((row, i) => (
                      <tr key={i}>
                        {row.map((v, j) => (
                          <td key={j} className="mono">
                            {typeof v === "number" ? (Number.isInteger(v) ? v : v.toFixed(4)) : String(v)}
                          </td>
                        ))}
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </>
          ) : (
            <div className="muted">{error ?? "Loading…"}</div>
          )}
        </div>
        <div className="modal-foot">
          {receipt?.verified_at_capture !== undefined && (
            <span className={`verify ${receipt.verified_at_capture ? "ok" : "bad"}`}>
              {receipt.verified_at_capture ? "✓ Verified at capture" : "✗ Not verified at capture"}
              <span className="mono">recorded run · hash {receipt.result_hash.replace("sha256:", "").slice(0, 16)}</span>
            </span>
          )}
          {!agent && !demo && (
            <button className="btn primary" onClick={run} disabled={!receipt || running}>
              {running ? "Re-running…" : "Re-run SQL"}
            </button>
          )}
          {rerun ? (
            <span className={`verify ${rerun.matches ? "ok" : "bad"}`}>
              {rerun.matches ? "✓ Same hash" : "✗ Hash differs"}
              <span className="mono">
                {rerun.result_hash.replace("sha256:", "")} · {rerun.rows} {rerun.rows === 1 ? "row" : "rows"} · {rerun.ms.toFixed(1)} ms · {rerun.world}
              </span>
            </span>
          ) : receipt?.verified_at_capture !== undefined ? null : (
            <span className="verify">
              {error && receipt
                ? error
                : agent || demo
                  ? "An agent receipt: the verifier re-derived every number from it before the number was shown."
                  : "Runs the exact SQL again at the pinned as_of and compares the hash."}
            </span>
          )}
        </div>
      </div>
    </>
  );
}
