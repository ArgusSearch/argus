// Receipts: every number links to the query that produced it; the drawer re-runs it and compares hashes.

import { createContext, useCallback, useContext, useEffect, useState, type ReactNode } from "react";
import { api } from "../lib/api";
import { hhmm, dayLabel, quantity } from "../lib/format";
import type { Quantity, Receipt, RerunResult } from "../lib/types";
import { ErrorState, explainError, Skeleton } from "../ui";

const ReceiptContext = createContext<(id: string) => void>(() => {});

export function useOpenReceipt(): (id: string) => void {
  return useContext(ReceiptContext);
}

export function ReceiptProvider({ children }: { children: ReactNode }) {
  const [open, setOpen] = useState<string | null>(null);
  const openReceipt = useCallback((id: string) => setOpen(id), []);
  const close = useCallback(() => setOpen(null), []);
  return (
    <ReceiptContext.Provider value={openReceipt}>
      {children}
      {open && <ReceiptDrawer id={open} onClose={close} />}
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

function ReceiptDrawer({ id, onClose }: { id: string; onClose: () => void }) {
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  const [error, setError] = useState<unknown>(null);
  const [runError, setRunError] = useState<unknown>(null);
  const [attempt, setAttempt] = useState(0);
  const [rerun, setRerun] = useState<RerunResult | null>(null);
  const [running, setRunning] = useState(false);

  useEffect(() => {
    let live = true;
    setReceipt(null);
    setRerun(null);
    setError(null);
    setRunError(null);
    api.receipt(id).then(
      (r) => live && setReceipt(r),
      (e: unknown) => live && setError(e),
    );
    return () => {
      live = false;
    };
  }, [id, attempt]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const run = async () => {
    setRunning(true);
    setRunError(null);
    try {
      setRerun(await api.rerun(id));
    } catch (e) {
      setRunError(e);
    } finally {
      setRunning(false);
    }
  };

  const runWhy = runError ? explainError(runError, `/receipts/${id}/rerun`) : null;

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
            </>
          ) : (
            error ? <ErrorState error={error} route={`/receipts/${id}`} onRetry={() => setAttempt((n) => n + 1)} /> : <Skeleton lines={5} label="Loading the receipt" />
          )}
        </div>
        <div className="modal-foot">
          <button className="btn primary" onClick={run} disabled={!receipt || running}>
            {running ? "Re-running…" : "Re-run SQL"}
          </button>
          {rerun ? (
            <span className={`verify ${rerun.matches ? "ok" : "bad"}`}>
              {rerun.matches ? "✓ Same hash" : "✗ Hash differs"}
              <span className="mono">
                {rerun.result_hash.replace("sha256:", "")} · {rerun.rows} {rerun.rows === 1 ? "row" : "rows"} · {rerun.ms.toFixed(1)} ms · {rerun.world}
              </span>
            </span>
          ) : (
            <span className="verify">
              {runWhy ? `${runWhy.title}. ${runWhy.detail}` : "Runs the exact SQL again at the pinned as_of and compares the hash."}
            </span>
          )}
        </div>
      </div>
    </>
  );
}
