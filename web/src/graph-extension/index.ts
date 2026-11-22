// The graph extension for any surface (classic Mission Control or the fx workspace):
//
//   const ext = useGraphExtension(() => api.graph().then(setGraph));   // refetch the graph when it changed
//   <GraphExtensionLayer ext={ext} />                                  // inside a position: relative panel
//
// or just the card: <NewMetricCard placement={ext.current} />. See docs/ext/graph-extension.md.
import "./graph-extension.css";

export { extensionApi } from "./api";
export { GraphExtensionLayer, placedNodeStyles } from "./GraphExtensionLayer";
export { placementView, placedNodes } from "./model";
export { NewMetricCard } from "./NewMetricCard";
export { PlacementDiagram } from "./PlacementDiagram";
export type { ExtensionState, MetricDefinition, PlacementResult } from "./types";
export { useGraphExtension, type GraphExtension } from "./useGraphExtension";
