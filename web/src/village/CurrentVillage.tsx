import { useEffect, useLayoutEffect, useMemo, useRef, useState } from "react";
import { useAgent } from "../fx/workspace/agent";
import { useAppState } from "../lib/AppState";
import { agentApi, type ProposalView } from "../lib/agent";
import { monitoringText } from "../lib/format";
import type { Graph } from "../lib/types";
import { ApprovalCard, Bubbles, Caption, FileTag, RolePanel } from "./Overlay";
import { VillageHeader, VillageStage } from "./VillageStage";
import { currentVillage } from "./current";
import type { Beat } from "./beats";
import { Player } from "./player";
import type { RoleId } from "./roles";
import { timeline } from "./timeline";
import type { Decision } from "./types";

export function CurrentVillage({ graph, onMetricMap }: { graph: Graph | null; onMetricMap?: () => void }) {
  const { view, monitor } = useAppState();
  const agent = useAgent();
  const village = useMemo(() => currentVillage(view, monitor, agent, graph), [view, monitor, agent, graph]);
  const { state, avatars, views, caseLabel, telemetry } = village;
  const [anchors] = useState(() => new Map<string, HTMLElement>());
  // Animate handoffs between real steps without advancing the application's snapshot.
  const [player] = useState(() => new Player());
  const previousBeat = useRef<Beat | null>(null);
  const beat = state.beat;
  useLayoutEffect(() => {
    const previous = previousBeat.current;
    previousBeat.current = beat;
    if (beat?.key === previous?.key && beat?.role === previous?.role && beat?.caseId === previous?.caseId) return;
    if (beat?.caseId && previous?.caseId === beat.caseId && previous.role !== beat.role) {
      const motion = timeline([previous, beat]);
      player.load(motion);
      player.seek(motion.slots[1].start);
      player.start();
    } else {
      player.stop();
      player.load(timeline([]));
    }
  }, [beat, player]);
  useEffect(() => () => player.stop(), [player]);
  const [selected, setSelected] = useState<RoleId | null>(null);
  const [approval, setApproval] = useState<ProposalView | null>(null);
  const [deciding, setDeciding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const openCount = monitor.openIncidents.length;
  const status = monitor.connection === "offline" ? "Shop offline"
    : !monitor.time ? "Waiting for data"
    : openCount ? `${openCount} open ${openCount === 1 ? "incident" : "incidents"}`
    : monitor.activeInvestigation ? "Investigating"
    : state.gate ? "Needs approval"
    : monitor.activityRole ? "Agents at work" : "Watching the shop";

  const gate = state.gate?.proposal && approval?.id === state.gate.proposal.id && approval.digest === state.gate.proposal.digest
    ? state.gate
    : null;
  const decide = async (decision: Decision) => {
    const proposal = monitor.pending;
    if (!gate?.proposal || !proposal || deciding) return;
    setDeciding(true);
    setError(null);
    try {
      agent.put(await agentApi.decide(proposal.id, decision, proposal.digest));
      setApproval(null);
    } catch (e) {
      setError(monitoringText((e as Error).message));
      agent.refresh();
    } finally {
      setDeciding(false);
    }
  };

  return (
    <VillageStage player={player} state={state} avatars={avatars} telemetry={telemetry} anchors={anchors} onSelect={setSelected}
      pins={<>
        <Bubbles views={views} anchors={anchors} player={player} onSelect={setSelected} selected={selected} onNeed={() => {
          setError(null);
          setApproval(monitor.pending ?? null);
        }} />
        <FileTag anchors={anchors} caseId={caseLabel} waiting={Boolean(state.gate)} />
      </>}
    >
      <VillageHeader onMetricMap={onMetricMap} />
      <div className="vl-hud vl-hud-tr" data-no-pick>
        <div className="vl-meta">
          {monitor.timeLabel && <b className="vl-shop-time">{monitor.timeLabel}</b>}
          <span>{status}</span>
        </div>
      </div>
      <div className="vl-hud vl-hud-bc" data-no-pick>
        <Caption state={state} avatars={avatars} />
      </div>
      {selected && <RolePanel role={selected} state={state} cue={avatars[selected]} onClose={() => setSelected(null)} />}
      {gate && <ApprovalCard gate={gate} live busy={deciding} error={error} onDecide={decide} onClose={() => setApproval(null)} />}
    </VillageStage>
  );
}
