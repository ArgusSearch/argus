// The style layer's root. Without the flag it renders its children and nothing else. With the flag it sets
// <html data-fx> (I1), renders the stage element (I3) and the loader, loads the rest of the layer and plays the
// opening: loader, then the shell and the scene's materialize intro together.

import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-500.css";
import "./tokens.css";
import "./base.css";
import { createContext, useContext, useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { emitIntro, FX_SCENE_READY, markStageReady, onStageReady, whenStageReady } from "./events";
import { fxFlags, type FxFlags, type FxTheme } from "./flag";
import { preloadScene, sceneAvailable } from "./GraphStage";
import { timeline, tokenMs } from "./motion";
import { FxDebug } from "./ui/FxDebug";
import { Loader } from "./ui/Loader";

/** boot: the loader covers the app; intro: the shell arrives; ready: everything settled. */
export type FxPhase = "boot" | "intro" | "ready";

/** The loader stays at least this long, so it reads as a beat and not as a flicker. */
const LOADER_MIN_MS = 900;
/** It waits for the scene's first frame until this time after navigation start at the latest... */
const SCENE_CAP_MS = 2200;
/** ...and for fx.css and the fonts until this time: an unstyled page is worse than a longer loader. */
const STYLES_CAP_MS = 8000;

const flags = fxFlags();
if (flags.theme) boot(flags.theme);

/** Runs once at module evaluation, before React's first render, so the first paint already has the theme. */
function boot(theme: FxTheme) {
  const root = document.documentElement;
  root.dataset.fx = theme;
  root.dataset.fxPhase = "boot";
  window.addEventListener(FX_SCENE_READY, markStageReady);
  // no scene on this page load: nothing will report a first frame, the classic graph needs no wait
  if (!sceneAvailable()) markStageReady();
  else void preloadScene()?.catch(() => undefined);
}

interface FxState extends FxFlags {
  on: boolean;
  phase: FxPhase;
}

const FxContext = createContext<FxState>({ ...flags, on: false, phase: "ready" });

/** The flags of this page load and the phase of the opening. */
export function useFx(): FxState {
  return useContext(FxContext);
}

export function StyleProvider({ children }: { children: ReactNode }) {
  if (!flags.theme) return <>{children}</>;
  return <FxShell flags={flags}>{children}</FxShell>;
}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, Math.max(0, ms)));
}

function loadFonts(): Promise<unknown> {
  if (!document.fonts) return Promise.resolve();
  return Promise.all([
    document.fonts.load('400 13px "IBM Plex Mono"'),
    document.fonts.load('500 13px "IBM Plex Mono"'),
  ]).catch(() => undefined);
}

function FxShell({ flags, children }: { flags: FxFlags; children: ReactNode }) {
  const [phase, setPhase] = useState<FxPhase>("boot");
  const [loader, setLoader] = useState<"shown" | "leaving" | "gone">(flags.intro ? "shown" : "gone");
  const phaseRef = useRef(phase);

  useLayoutEffect(() => {
    phaseRef.current = phase;
    document.documentElement.dataset.fxPhase = phase;
  }, [phase]);

  useEffect(() => {
    let live = true;
    let cancel = () => {};
    const styles = import("./styles").catch((error: unknown) => console.warn("[fx] the style layer failed to load", error));
    const ready = Promise.race([Promise.all([styles, loadFonts()]), sleep(STYLES_CAP_MS - performance.now())]);
    const introMs = () => (flags.intro ? tokenMs("--fx-dur-intro", 3000) : 0);

    if (flags.intro) {
      const scene = Promise.race([whenStageReady(), sleep(SCENE_CAP_MS - performance.now())]);
      Promise.all([ready, scene, sleep(LOADER_MIN_MS)]).then(() => {
        if (!live) return;
        const fade = tokenMs("--fx-dur-reveal", 750);
        // the shell's last entrance (fx.css, intro phase) starts at 7 staggers and runs for --fx-dur-slow
        const shell = tokenMs("--fx-dur-slow", 1250) + 7 * tokenMs("--fx-stagger", 100);
        setLoader("leaving");
        setPhase("intro");
        emitIntro(introMs());
        cancel = timeline([
          [fade, () => setLoader("gone")],
          [Math.max(fade, shell), () => setPhase("ready")],
        ]);
      });
    } else {
      ready.then(() => {
        if (!live) return;
        setPhase("ready");
        emitIntro(0);
      });
    }

    // a scene that reports its first frame after the loader is gone (late, or mounted again) still gets its cue
    const offStage = onStageReady(() => {
      if (phaseRef.current !== "boot") emitIntro(introMs());
    });
    return () => {
      live = false;
      cancel();
      offStage();
    };
  }, [flags.intro]);

  return (
    <FxContext.Provider value={{ ...flags, on: true, phase }}>
      <div id="fx-stage" aria-hidden="true" />
      {children}
      {flags.debug && <FxDebug />}
      {loader !== "gone" && <Loader leaving={loader === "leaving"} />}
    </FxContext.Provider>
  );
}
