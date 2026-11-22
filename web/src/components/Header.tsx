import type { ConnectionState } from "../lib/api";
import { useAppState } from "../lib/AppState";
import { exampleShopName } from "../lib/deployment";
import type { RunView } from "../lib/store";
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
  const { monitor } = useAppState();
  const mode = connection === "open" ? (view.mode ?? health?.mode ?? "connecting") : connection;
  const tr = useText();
  return (
    <header className="header">
      <div className="brand">
        <Mark />
        <span className="brand-name">ARGUS</span>
        <span className="brand-sub">Mission Control</span>
      </div>
      <div className="clock" title="Shop time in UTC">
        <span className="clock-time">{monitor.timeLabel ?? "Waiting for shop data"}</span>
      </div>
      <span className="spacer" />
      <span className={`mode ${mode}`}>
        <span className="dot" />
        {mode === "offline" ? "API offline" : mode === "connecting" ? "Connecting to API" : presenting || mode === "replay"
          ? tr("Example shop history") : `Live · ${exampleShopName}`}
      </span>
      <AgentRecordingLink />
    </header>
  );
}
