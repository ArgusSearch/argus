import type { ConnectionState } from "../lib/api";
import { dayLabel, hhmm } from "../lib/format";
import { scoringHour, type RunView } from "../lib/store";
import type { Health } from "../lib/types";
import { AgentRecordingLink } from "../fx/workspace/AgentRunControls";
import { FacetMark } from "../fx/entry/brand";
import { useText } from "../settings/language";

/** The Argus mark (C - Facet) in the current text color, with its lilac core. */
export function Mark() {
  return <FacetMark className="brand-mark" />;
}

export function Header({
  view,
  health,
  connection,
  presenting,
}: {
  view: RunView;
  health: Health | null;
  connection: ConnectionState;
  presenting: boolean;
}) {
  const mode = connection === "open" ? (view.mode ?? health?.mode ?? "connecting") : connection;
  const tr = useText();
  return (
    <header className="header">
      <div className="brand">
        <Mark />
        <span className="brand-name">ARGUS</span>
        <span className="brand-sub">Mission Control</span>
      </div>
      <div className="clock" title="Time of the latest check">
        <span className="clock-time">
          {view.simTs ? `${dayLabel(view.simTs)} · ${hhmm(view.simTs)}` : "waiting for the first tick"}
        </span>
        {view.tick && <span className="clock-sub">checking data up to {hhmm(scoringHour(view))}</span>}
      </div>
      <span className="spacer" />
      <span className={`mode ${mode}`}>
        <span className="dot" />
        {mode === "offline" ? "API offline" : mode === "connecting" ? "Connecting to API" : presenting || mode === "replay"
          ? tr("Example shop history") : `Live · ${tr("Example shop")}`}
      </span>
      <AgentRecordingLink />
    </header>
  );
}
