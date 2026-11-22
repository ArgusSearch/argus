// The village as lane E's workspace mounts it (web/src/fx/workspace/Workspace.tsx loads this file when it
// exists): the page with its "Metric map" sub-view wired to the workspace's visualization page.
import type { RunView } from "../lib/store";
import type { Graph } from "../lib/types";
import { go } from "../fx/nav";
import { staticReplay } from "../lib/deployment";
import { CurrentVillage } from "./CurrentVillage";

export interface VillageProps {
  graph: Graph | null;
  view: RunView;
  onSelectNode: (id: string) => void;
}

export default function Village({ graph }: VillageProps) {
  return <CurrentVillage graph={graph} onMetricMap={staticReplay ? undefined : () => go("graph")} />;
}

export { Village };
