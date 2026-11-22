// Shared loading, empty and error states. Styles live in ./ui.css and reuse the variables of styles.css.

import { useEffect, useState, type ReactNode } from "react";
import type { ConnectionState } from "../lib/api";
import { explainError } from "./errors";
import "./ui.css";

export function Spinner({ size = 16, label = "Loading" }: { size?: number; label?: string }) {
  return (
    <svg className="ui-spinner" width={size} height={size} viewBox="0 0 16 16" role="status" aria-label={label}>
      <circle cx="8" cy="8" r="6.2" fill="none" stroke="currentColor" strokeOpacity="0.22" strokeWidth="1.8" />
      <path d="M8 1.8a6.2 6.2 0 0 1 6.2 6.2" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" />
    </svg>
  );
}

/** A spinner with a line of text, shown only after `delay` ms so fast answers never flash. */
export function Loading({ label = "Loading", delay = 250 }: { label?: string; delay?: number }) {
  const [shown, setShown] = useState(delay <= 0);
  useEffect(() => {
    if (delay <= 0) return;
    const timer = setTimeout(() => setShown(true), delay);
    return () => clearTimeout(timer);
  }, [delay]);
  return (
    <div className="ui-loading" aria-busy="true">
      {shown && (
        <>
          <Spinner label={label} />
          <span>{label}…</span>
        </>
      )}
    </div>
  );
}

type SkeletonVariant = "lines" | "card" | "sheet" | "graph";

/** Placeholder shapes in the size of what is coming, so the layout does not jump when it arrives. */
export function Skeleton({ variant = "lines", lines = 3, label = "Loading" }: { variant?: SkeletonVariant; lines?: number; label?: string }) {
  if (variant === "graph") {
    return (
      <div className="ui-skel-graph" role="status" aria-label={label}>
        {Array.from({ length: 4 }, (_, col) => (
          <div key={col} className="ui-skel-col">
            {Array.from({ length: col === 0 ? 3 : 5 - col }, (_, row) => (
              <span key={row} className="ui-skel ui-skel-node" />
            ))}
          </div>
        ))}
      </div>
    );
  }
  if (variant === "card") {
    return (
      <div className="ui-skel-card" role="status" aria-label={label}>
        <span className="ui-skel" style={{ width: "38%", height: 10 }} />
        <span className="ui-skel" style={{ width: "82%", height: 14 }} />
        <span className="ui-skel" style={{ width: "64%", height: 10 }} />
      </div>
    );
  }
  if (variant === "sheet") {
    return (
      <div className="ui-skel-sheet" role="status" aria-label={label}>
        <span className="ui-skel" style={{ width: "56%", height: 20 }} />
        <span className="ui-skel" style={{ width: "100%", height: 56 }} />
        <span className="ui-skel" style={{ width: "100%", height: 140 }} />
        <span className="ui-skel" style={{ width: "72%", height: 12 }} />
        <span className="ui-skel" style={{ width: "88%", height: 12 }} />
      </div>
    );
  }
  return (
    <div className="ui-skel-lines" role="status" aria-label={label}>
      {Array.from({ length: lines }, (_, i) => (
        <span key={i} className="ui-skel" style={{ width: `${92 - ((i * 17) % 40)}%` }} />
      ))}
    </div>
  );
}

export function EmptyState({ title, detail, children }: { title: string; detail?: ReactNode; children?: ReactNode }) {
  return (
    <div className="ui-empty">
      <svg className="ui-empty-mark" width="28" height="28" viewBox="0 0 32 32" aria-hidden>
        <path d="M3 16c3.6-6 8-9 13-9s9.4 3 13 9c-3.6 6-8 9-13 9s-9.4-3-13-9Z" fill="none" stroke="currentColor" strokeWidth="1.6" />
        <circle cx="16" cy="16" r="4.6" fill="none" stroke="var(--probe)" strokeWidth="1.6" />
      </svg>
      <div className="ui-empty-title">{title}</div>
      {detail && <div className="ui-empty-detail">{detail}</div>}
      {children}
    </div>
  );
}

/** A failed request: what went wrong in plain English, the route that failed, and a retry when it can help. */
export function ErrorState({ error, route, onRetry, compact = false }: { error: unknown; route?: string; onRetry?: () => void; compact?: boolean }) {
  const e = explainError(error, route);
  return (
    <div className={`ui-error${compact ? " compact" : ""}`} role="alert">
      <div className="ui-error-title">{e.title}</div>
      <div className="ui-error-detail">{e.detail}</div>
      <div className="ui-error-foot">
        {route && <span className="mono">{route}</span>}
        {onRetry && e.retry && (
          <button className="btn" onClick={onRetry}>
            Try again
          </button>
        )}
      </div>
    </div>
  );
}

/**
 * The connection to the API, said once at the top of the page. Silent while connected; "Connecting" on a slow
 * first load; "The API is not running" or "Lost the connection" with a running clock while it is down. The
 * stream retries by itself; Reload is there for a stream that closed (before follow() reopened closed streams).
 */
export function OfflineBanner({ connection, apiUp }: { connection: ConnectionState; apiUp?: boolean | null }) {
  const [everOpen, setEverOpen] = useState(false);
  const [everClosed, setEverClosed] = useState(false);
  const [since, setSince] = useState<number | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const down = connection !== "open" || apiUp === false;

  useEffect(() => {
    if (connection === "offline") setEverClosed(true);
  }, [connection]);

  useEffect(() => {
    if (!down) {
      setEverOpen(true);
      setEverClosed(false);
      setSince(null);
      return;
    }
    setSince((s) => s ?? Date.now());
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [down]);

  if (!down) return null;
  const seconds = since ? Math.max(0, Math.round((now - since) / 1000)) : 0;
  // the state flips between offline and connecting on every retry: what was seen once stays said
  const notRunning = everClosed || connection === "offline" || apiUp === false;
  // a first connect that takes under 2 s is not worth a banner
  if (!everOpen && !notRunning && seconds < 2) return null;

  const title = everOpen ? "Lost the connection to the API" : notRunning ? "The API is not running" : "Connecting to Argus";
  return (
    <div className={`ui-offline${everOpen || notRunning ? " down" : ""}`} role="status" aria-live="polite">
      <Spinner size={13} label="Retrying" />
      <span className="ui-offline-title">{title}</span>
      <span className="ui-offline-detail">
        Retrying on its own{seconds >= 2 ? ` · ${seconds} s` : ""}.
      </span>
      {notRunning && (
        <button className="btn" onClick={() => window.location.reload()}>
          Reload
        </button>
      )}
    </div>
  );
}
