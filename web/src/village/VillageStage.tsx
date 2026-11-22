import { Component, lazy, Suspense, useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import type { AvatarCues } from "./avatars/state";
import type { Player } from "./player";
import type { RoleId } from "./roles";
import type { MarketVerdict, WatchSeries } from "./telemetry";
import type { VillageState } from "./timeline";
import { Village2D } from "./Village2D";
import "./village.css";

const VillageScene = lazy(() => import("./scene/VillageScene"));

let webgl2: boolean | null = null;
function hasWebGL2(): boolean {
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

class SceneBoundary extends Component<{ onFail: (error: Error) => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error) {
    this.props.onFail(error);
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export function VillageStage({ player, state, avatars, telemetry, anchors, onSelect, pins, children }: {
  player: Player;
  state: VillageState;
  avatars: AvatarCues;
  telemetry: { watch: WatchSeries[]; market: MarketVerdict | null };
  anchors: Map<string, HTMLElement>;
  onSelect: (role: RoleId) => void;
  pins: ReactNode;
  children: ReactNode;
}) {
  const [stage, setStage] = useState<"3d" | "2d">(() =>
    typeof window === "undefined" || new URLSearchParams(window.location.search).get("village2d") === "1" || !hasWebGL2() ? "2d" : "3d");
  const onFail = useCallback((error: Error) => {
    console.warn("village: 3D stage unavailable, using the 2D stage", error);
    setStage("2d");
  }, []);
  const root = useRef<HTMLElement>(null);
  useEffect(() => {
    const el = root.current;
    if (!el) return;
    const fit = () => {
      const top = Math.max(0, el.getBoundingClientRect().top + window.scrollY);
      const bottom = top > 0 ? 16 : 0;
      el.style.height = `${Math.max(520, window.innerHeight - top - bottom)}px`;
    };
    fit();
    window.addEventListener("resize", fit);
    const ro = new ResizeObserver(fit);
    if (el.parentElement) ro.observe(el.parentElement);
    return () => {
      window.removeEventListener("resize", fit);
      ro.disconnect();
    };
  }, []);
  return (
    <section ref={root} className={`vl-root vl-${stage}`} aria-label="Argus village">
      <div className="vl-stage">
        {stage === "3d" ? (
          <SceneBoundary onFail={onFail}>
            <Suspense fallback={<div className="vl-loading">Building the village…</div>}>
              <VillageScene player={player} state={state} avatars={avatars} telemetry={telemetry} anchors={anchors} onSelect={onSelect} onHover={() => undefined} onFail={onFail} />
            </Suspense>
          </SceneBoundary>
        ) : (
          <Village2D player={player} state={state} avatars={avatars} anchors={anchors} onSelect={onSelect} />
        )}
        {pins}
      </div>
      {children}
    </section>
  );
}

export function VillageHeader({ onMetricMap }: { onMetricMap?: () => void }) {
  return (
    <header className="vl-hud vl-hud-tl" data-no-pick>
      <span className="vl-kicker">// Argus village</span>
      <h1>Seven agents, one igloo each</h1>
      {onMetricMap && (
        <nav className="vl-seg" aria-label="sub-view">
          <button className="on" aria-current="page">Village</button>
          <button onClick={onMetricMap}>Metric map</button>
        </nav>
      )}
    </header>
  );
}
