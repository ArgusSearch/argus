import { useEffect, useState } from "react";
import { AgentRunControls } from "../fx/workspace/AgentRunControls";
import { api } from "../lib/api";
import type { Health, ReplayStatus } from "../lib/types";
import { useText } from "./language";
import { Btn, Card, Row, Switch } from "./ui";

const SPEEDS = [1, 2, 4, 8];

export function DeveloperTab() {
  const tr = useText();
  const [enabled, setEnabled] = useState(false);
  const [health, setHealth] = useState<Health | null>(null);
  const [run, setRun] = useState<ReplayStatus | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!enabled) return;
    let active = true;
    void api.recordingHealth().then((next) => {
      if (!active) return;
      setHealth(next);
      setRun(next.run);
    }, () => {
      if (active) setError("The recording source could not be reached.");
    });
    return () => { active = false; };
  }, [enabled]);

  const control = (body: Parameters<typeof api.replay>[0]) => {
    setError(null);
    void api.replay(body).then(setRun, () => setError("The recording controls could not be updated."));
  };

  return (
    <Card title="Time-lapse">
      <Row label="Enable recording controls">
        <Switch label="Enable recording controls" on={enabled} onChange={(on) => {
          setEnabled(on);
          setError(null);
        }} />
      </Row>
      {enabled && <>
        <Row label="Time-lapse speed">
          <div className="controls" aria-label={tr("Time-lapse speed")}>
            <button className="ctl" disabled={!run} onClick={() => control({
              action: run?.playing ? "pause" : run?.finished && health?.mode === "replay" ? "restart" : "play",
            })}>{tr(run?.playing ? "Pause" : "Play")}</button>
            {SPEEDS.map((speed) => (
              <button key={speed} className={`ctl${run?.speed === speed ? " on" : ""}`}
                aria-pressed={run?.speed === speed} disabled={!run} onClick={() => control({ speed })}>{speed}×</button>
            ))}
            {health?.mode === "replay" && <Btn onClick={() => control({ action: "restart" })}>{tr("Restart")}</Btn>}
          </div>
        </Row>
        <Row label="Recording workspace">
          <a className="btn" href="/?demo=1&captions=1&fx=1">{tr("Open recording workspace")}</a>
        </Row>
        <AgentRunControls />
        {error && <p className="cs-note" role="status">{tr(error)}</p>}
      </>}
    </Card>
  );
}
