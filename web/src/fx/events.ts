// The window events between the style layer and the scene (report section 3.4, I7), and the layer's own
// "the graph area shows something" signal that releases the loader.

/** Sent by the scene: its first frame is on screen, the loader may fade. */
export const FX_SCENE_READY = "fx:scene-ready";
/** Sent by the layer when the loader fades: start the materialize intro. */
export const FX_INTRO = "fx:intro";
/** Sent by the scene on every quality change. */
export const FX_QUALITY = "fx:quality";
/** Sent by the layer when data-fx changes: the scene re-reads the tokens. */
export const FX_THEME = "fx:theme";

export interface FxIntroDetail {
  /** Length of the materialize intro in ms; 0 means appear at once. */
  duration: number;
}

export interface FxQualityDetail {
  tier: string;
  pixelRatio: number;
  fps: number;
}

export function emitIntro(duration: number): void {
  window.dispatchEvent(new CustomEvent<FxIntroDetail>(FX_INTRO, { detail: { duration: Math.max(0, Math.round(duration)) } }));
}

type Listener = () => void;
const listeners = new Set<Listener>();
let ready = false;

/** The graph area shows something: the scene's first frame, or the classic graph when the scene is not used. */
export function markStageReady(): void {
  ready = true;
  for (const listener of [...listeners]) listener();
}

export function stageReady(): boolean {
  return ready;
}

/** Calls `listener` on every later markStageReady (a scene that mounts again reports again). */
export function onStageReady(listener: Listener): () => void {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

/** Resolves on the first markStageReady, at once when it already happened. */
export function whenStageReady(): Promise<void> {
  if (ready) return Promise.resolve();
  return new Promise((resolve) => {
    const off = onStageReady(() => {
      off();
      resolve();
    });
  });
}
