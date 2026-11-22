// The village as lane E's workspace mounts it (web/src/fx/workspace/Workspace.tsx loads this file when it
// exists): the page with its "Metric map" sub-view wired to the workspace's visualization page.
import type { RunView } from "../lib/store";
import type { Graph } from "../lib/types";
import { go } from "../fx/nav";
import { ArgusVillage } from "./ArgusVillage";
import { useAgent } from "../fx/workspace/agent";

export interface VillageProps {
  graph: Graph | null;
  view: RunView;
  onSelectNode: (id: string) => void;
}

export default function Village(_props: VillageProps) {
  const agent = useAgent();
  const liveAvatars = agent.enabled && !agent.scope?.startsWith("demo:") ? agent.avatars : undefined;
  return <ArgusVillage onMetricMap={() => go("graph")} liveAvatars={liveAvatars} onLiveDecision={agent.refresh} />;
}

export { Village };
