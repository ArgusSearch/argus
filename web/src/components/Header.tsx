import { api, type ConnectionState } from "../lib/api";
import { dayLabel, hhmm } from "../lib/format";
import { scoringHour, type RunView } from "../lib/store";
import type { Health } from "../lib/types";

const SPEEDS = [1, 2, 4, 8];

export function Mark() {
  return (
    <svg className="brand-mark" viewBox="0 0 32 32" aria-hidden>
      <path d="M3 16c3.6-6 8-9 13-9s9.4 3 13 9c-3.6 6-8 9-13 9s-9.4-3-13-9Z" fill="none" stroke="#e7ebf3" strokeWidth="1.8" />
      <circle cx="16" cy="16" r="5.2" fill="none" stroke="#5aa7ff" strokeWidth="1.8" />
      <circle cx="16" cy="16" r="1.9" fill="#e7ebf3" />
    </svg>
  );
}

export function Header({
  view,
  health,
  connection,
  onDigest,
  presenting,
}: {
  view: RunView;
  health: Health | null;
  connection: ConnectionState;
  onDigest: () => void;
  presenting: boolean;
}) {
  const replay = connection === "open" && !presenting ? health?.run ?? null : null;
  const mode = connection === "open" ? (view.mode ?? health?.mode ?? "connecting") : connection;
  const world = health?.source.split("/").slice(-2, -1)[0];
  const control = (body: Parameters<typeof api.replay>[0]) => void api.replay(body).catch(() => undefined);
  return (
    <header className="header">
      <div className="brand">
        <Mark />
        <span className="brand-name">ARGUS</span>
        <span className="brand-sub">Mission Control</span>
      </div>
      <div className="clock" title="simulated clock (as_of of the last tick)">
        <span className="clock-time">
          {view.simTs ? `${dayLabel(view.simTs)} · ${hhmm(view.simTs)}` : "waiting for the first tick"}
        </span>
        {view.tick && <span className="clock-sub">checking data up to {hhmm(scoringHour(view))}</span>}
      </div>
      <span className="spacer" />
      <span className={`mode ${mode}`} title={presenting ? undefined : health?.source}>
        <span className="dot" />
        {mode === "offline" ? "API offline" : mode === "connecting" ? "Connecting to API" : presenting
          ? "Agent replay · recorded run" : mode === "live" ? `Live${world ? ` · ${world}` : ""}` : "Replay · recorded run"}
      </span>
      {replay && (
        <>
          <div className="controls" aria-label="replay controls">
            <button
              className="ctl"
              aria-label={replay.playing ? "Pause" : "Play"}
              onClick={() => control({ action: replay.playing ? "pause" : replay.finished && mode === "replay" ? "restart" : "play" })}
            >
              {replay.playing ? (
                <svg width="12" height="12" viewBox="0 0 12 12">
                  <rect x="2" y="1.5" width="3" height="9" rx="1" fill="currentColor" />
                  <rect x="7" y="1.5" width="3" height="9" rx="1" fill="currentColor" />
                </svg>
              ) : (
                <svg width="12" height="12" viewBox="0 0 12 12">
                  <path d="M3 1.8v8.4L10 6Z" fill="currentColor" />
                </svg>
              )}
            </button>
            {SPEEDS.map((s) => (
              <button key={s} className={`ctl${replay.speed === s ? " on" : ""}`} onClick={() => control({ speed: s })}>
                {s}×
              </button>
            ))}
            {mode === "replay" && (
              <button className="ctl" aria-label="Restart" title="Restart the replay" onClick={() => control({ action: "restart" })}>
                <svg width="13" height="13" viewBox="0 0 14 14">
                  <path d="M2.5 7a4.5 4.5 0 1 0 1.4-3.3M2.5 1.8v2.4h2.4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
                </svg>
              </button>
            )}
          </div>
          <div className="progress" title={`${replay.position} of ${replay.total} ${mode === "live" ? "hours" : "events"}`}>
            <div style={{ width: `${(100 * replay.position) / Math.max(replay.total, 1)}%` }} />
          </div>
        </>
      )}
      <button className="btn" onClick={onDigest}>
        While you slept
      </button>
    </header>
  );
}
