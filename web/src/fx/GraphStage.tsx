// Drop-in for GraphView. Without the flag it renders GraphView and nothing else, so the page is unchanged and
// the 3D chunk is never requested. With the flag it lazy-loads the scene (web/src/fx/scene/GraphScene.tsx,
// report section 3.4, I4) and falls back to the classic graph when that file is absent, WebGL2 is missing or
// the scene throws.

import { Component, lazy, Suspense, useEffect, type ComponentType, type ErrorInfo, type ReactNode } from "react";
import { GraphView } from "../components/GraphView";
import type { RunView } from "../lib/store";
import type { Graph } from "../lib/types";
import { markStageReady } from "./events";
import { fxOn } from "./flag";

/** The props of today's GraphView, which the scene takes as well (I4). */
export interface GraphSceneProps {
  graph: Graph;
  view: RunView;
  onSelectNode?: (id: string) => void;
}

type SceneModule = { default: ComponentType<GraphSceneProps> };

// import.meta.glob instead of import(): an absent scene folder builds to an empty map instead of failing
const sceneFiles = import.meta.glob<SceneModule>("./scene/GraphScene.tsx");
const importScene = sceneFiles["./scene/GraphScene.tsx"] as (() => Promise<SceneModule>) | undefined;

let webgl2: boolean | null = null;

/** Whether this browser can create a WebGL2 context (checked once, the probe context is released). */
export function hasWebGL2(): boolean {
  if (webgl2 === null) {
    try {
      const gl = document.createElement("canvas").getContext("webgl2");
      webgl2 = gl !== null;
      gl?.getExtension("WEBGL_lose_context")?.loseContext();
    } catch {
      webgl2 = false;
    }
  }
  return webgl2;
}

/** Whether the scene will be used on this page load. */
export function sceneAvailable(): boolean {
  return fxOn() && importScene !== undefined && hasWebGL2();
}

let pending: Promise<SceneModule> | null = null;

/** Starts loading the scene chunk early (while the loader shows); a no-op when the scene is not used. */
export function preloadScene(): Promise<SceneModule> | null {
  if (!importScene || !sceneAvailable()) return null;
  pending ??= importScene();
  return pending;
}

const Scene = importScene ? lazy(() => preloadScene() ?? Promise.reject(new Error("scene unavailable"))) : null;

/** The classic graph inside the new shell; tells the loader the graph area is ready. */
function ClassicGraph(props: GraphSceneProps) {
  useEffect(() => markStageReady(), []);
  return <GraphView {...props} />;
}

class SceneBoundary extends Component<{ fallback: () => ReactNode; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: unknown, info: ErrorInfo) {
    console.warn("[fx] the 3D graph failed, showing the classic graph instead", error, info.componentStack);
  }

  render() {
    return this.state.failed ? this.props.fallback() : this.props.children;
  }
}

export function GraphStage(props: GraphSceneProps) {
  if (!fxOn()) return <GraphView {...props} />;
  if (!Scene || !sceneAvailable()) return <ClassicGraph {...props} />;
  return (
    <SceneBoundary fallback={() => <ClassicGraph {...props} />}>
      <Suspense fallback={null}>
        <Scene {...props} />
      </Suspense>
    </SceneBoundary>
  );
}
