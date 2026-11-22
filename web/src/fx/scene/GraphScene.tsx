// The metric graph as a 3D ice scene (report section 3.4, I4): a drop-in for GraphView with the same props.
// It renders one mount element that fills its parent; that element is the safe rectangle the graph is framed
// in and takes hover and clicks. The canvas goes into #fx-stage when the style layer provides it (a full-window
// layer behind the app), into the mount element otherwise (the lab page). Loaded lazily, default export.

import "./scene.css";
import { useEffect, useRef, useState } from "react";
import type { RunView } from "../../lib/store";
import type { Graph } from "../../lib/types";
import { SceneEngine } from "./engine";
import { qualityMode } from "./quality";

export interface GraphSceneProps {
  /** C3 graph from GET /graph: nodes, typed edges, logs. A new version may add nodes and edges. */
  graph: Graph;
  /** The folded C5 stream (lib/store.ts): tick, attention, edges, anomalies, incidents, notes, steps, focus, thresholds. */
  view: RunView;
  /** Called when a block is clicked; opens the existing NodeSheet. */
  onSelectNode?: (id: string) => void;
  /**
   * "full" (default): the graph's own view, canvas on the stage behind the app. "preview": a small card that
   * frames the affected path of the open incident, canvas inside the card, no intro choreography.
   */
  variant?: "full" | "preview";
}

export default function GraphScene({ graph, view, onSelectNode, variant = "full" }: GraphSceneProps) {
  const mount = useRef<HTMLDivElement>(null);
  const engine = useRef<SceneEngine | null>(null);
  const select = useRef(onSelectNode);
  const [failure, setFailure] = useState<Error | null>(null);
  // a scene that cannot run hands over to the error boundary around it, which shows the classic graph
  if (failure) throw failure;

  useEffect(() => {
    select.current = onSelectNode;
  }, [onSelectNode]);

  useEffect(() => {
    const el = mount.current;
    if (!el) return;
    const params = new URLSearchParams(window.location.search);
    let created: SceneEngine;
    try {
      created = new SceneEngine({
        mount: el,
        onSelect: (id) => select.current?.(id),
        onFail: setFailure,
        quality: qualityMode(window.location.search),
        skipIntro: params.get("fxintro") === "0",
        debug: variant === "full" && (params.get("fxdebug") === "1" || document.documentElement.dataset.fxLab === "1"),
        preview: variant === "preview",
      });
    } catch (error) {
      setFailure(error instanceof Error ? error : new Error(String(error)));
      return;
    }
    engine.current = created;
    return () => {
      created.dispose();
      engine.current = null;
    };
  }, [variant]);

  useEffect(() => {
    engine.current?.setInputs(graph, view);
  }, [graph, view, variant]);

  return <div ref={mount} className={`fxs-mount ${variant}`} data-fx-scene={variant} />;
}
