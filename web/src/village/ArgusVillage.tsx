// The Argus Village page: seven agents at work, one igloo each. Plays a recorded run (S4 by default) or
// follows the API live, and shows the existing metric map as its second sub-view through `onMetricMap`.
//
//   <ArgusVillage onMetricMap={() => go("graph")} />
//
// URL options: ?village=s1|s2|s4|s5|live (the source), ?village2d=1 (the 2D stage), ?vspeed=2 (start speed),
// ?vat=<seconds> (start at a time, for captures), fxq=low|mid|high (fixed quality).

import { Component, lazy, Suspense, useCallback, useEffect, useMemo, useRef, useState, type ErrorInfo, type ReactNode } from "react";
import { dayLabel, hhmm } from "../lib/format";
import { buildBeats } from "./beats";
import { ApprovalCard, Bubbles, Caption, FileTag, RolePanel, roleViews } from "./Overlay";
import { Player, SPEEDS } from "./player";
import { ROLES, type RoleId } from "./roles";
import { decideLive, followLive, initialSource, loadTape, SOURCES, type SourceId } from "./source";
import { idleBubbles, timeline, villageAt, type VillageState } from "./timeline";
import type { Decision, VillageTape } from "./types";
import { Village2D } from "./Village2D";
import "./village.css";

const VillageScene = lazy(() => import("./scene/VillageScene"));
const IDLE = idleBubbles(ROLES);

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

class SceneBoundary extends Component<{ onFail: (e: Error) => void; children: ReactNode }, { failed: boolean }> {
  state = { failed: false };
  static getDerivedStateFromError() {
    return { failed: true };
  }
  componentDidCatch(error: Error, _info: ErrorInfo) {
    this.props.onFail(error);
  }
  render() {
    return this.state.failed ? null : this.props.children;
  }
}

export interface ArgusVillageProps {
  /** opens the existing metric map (the shell's visualization page); the tab is hidden without it */
  onMetricMap?: () => void;
  /** the source to start on; default from ?village=, else the S4 replay */
  initial?: SourceId;
}

export function ArgusVillage({ onMetricMap, initial }: ArgusVillageProps) {
  const search = typeof window === "undefined" ? "" : window.location.search;
  const params = useMemo(() => new URLSearchParams(search), [search]);
  const [source, setSource] = useState<SourceId>(() => initial ?? initialSource(search));
  const [tape, setTape] = useState<VillageTape | null>(null);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [decision, setDecision] = useState<Decision | null>(null);
  const [live, setLive] = useState<{ state: string; agent: boolean }>({ state: "connecting", agent: false });
  const [selected, setSelected] = useState<RoleId | null>(null);
  const [approval, setApproval] = useState(false);
  const [deciding, setDeciding] = useState<{ busy: boolean; error: string | null }>({ busy: false, error: null });
  const [stage, setStage] = useState<"3d" | "2d">(() => (params.get("village2d") === "1" || !hasWebGL2() ? "2d" : "3d"));
  const anchors = useMemo(() => new Map<string, HTMLElement>(), []);
  const player = useMemo(() => {
    const p = new Player();
    const speed = Number(params.get("vspeed"));
    if ((SPEEDS as readonly number[]).includes(speed)) p.speed = speed;
    return p;
  }, [params]);
  const startAt = useRef(Number(params.get("vat")) || 0);
  // the clock, for headless captures and tests: window.__villagePlayer.seek(seconds)
  useEffect(() => {
    (window as unknown as { __villagePlayer?: Player }).__villagePlayer = player;
  }, [player]);

  // the tape: a recorded run, or the live stream
  useEffect(() => {
    setTape(null);
    setDecision(null);
    setApproval(false);
    setLoadError(null);
    setDeciding({ busy: false, error: null });
    player.follow = source === "live";
    if (source === "live") {
      return followLive(setTape, (state, agent) => setLive({ state, agent }));
    }
    const ctrl = new AbortController();
    loadTape(source, ctrl.signal).then(setTape, (e: Error) => {
      if (e.name !== "AbortError") setLoadError(e.message);
    });
    return () => ctrl.abort();
  }, [source, player]);

  // beats and the clock
  const beats = useMemo(() => (tape ? buildBeats(tape, { decision }) : []), [tape, decision]);
  const tapeKey = useRef<VillageTape | null>(null);
  useEffect(() => {
    const fresh = tapeKey.current?.scenario !== tape?.scenario || (source !== "live" && tapeKey.current !== tape);
    tapeKey.current = tape;
    player.load(timeline(beats), fresh && source !== "live");
    if (fresh && startAt.current) {
      player.seek(startAt.current);
      startAt.current = 0;
    }
  }, [beats, player, tape, source]);

  const [state, setState] = useState<VillageState>(() => villageAt(player.timeline, player.time, IDLE));
  useEffect(() => {
    const update = () => setState(villageAt(player.timeline, player.time, IDLE));
    update();
    const off = player.subscribe(update);
    player.start();
    return () => {
      off();
      player.stop();
    };
  }, [player]);

  const views = useMemo(() => roleViews(state, player), [state, player]);

  const decide = useCallback(
    async (d: Decision) => {
      const gate = state.gate;
      if (!gate) return;
      if (source === "live" && gate.proposal) {
        setDeciding({ busy: true, error: null });
        try {
          await decideLive(gate.proposal, d);
          setDeciding({ busy: false, error: null });
          setApproval(false);
        } catch (e) {
          setDeciding({ busy: false, error: `The API refused: ${(e as Error).message}` });
        }
        return;
      }
      setDecision(d);
      setApproval(false);
    },
    [state.gate, source],
  );

  const onFail = useCallback((e: Error) => {
    console.warn("village: 3D stage unavailable, using the 2D stage", e);
    setStage("2d");
  }, []);

  // fill the window below wherever the shell puts the page (the lab page starts at the top)
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

  const total = player.timeline.total;
  const progress = total ? Math.min(1, player.time / total) : 0;
  const caseId = state.beat?.caseId ?? null;

  return (
    <section ref={root} className={`vl-root vl-${stage}`} aria-label="Argus village">
      <div className="vl-stage">
        {stage === "3d" ? (
          <SceneBoundary onFail={onFail}>
            <Suspense fallback={<div className="vl-loading">Building the village…</div>}>
              <VillageScene player={player} state={state} anchors={anchors} onSelect={setSelected} onHover={() => undefined} onFail={onFail} />
            </Suspense>
          </SceneBoundary>
        ) : (
          <Village2D player={player} state={state} anchors={anchors} onSelect={setSelected} />
        )}
        <Bubbles views={views} anchors={anchors} player={player} onNeed={() => setApproval(true)} onSelect={setSelected} selected={selected} />
        <FileTag anchors={anchors} caseId={caseId} waiting={Boolean(state.gate)} />
      </div>

      <header className="vl-hud vl-hud-tl" data-no-pick>
        <span className="vl-kicker">// Argus village</span>
        <h1>Seven agents, one igloo each</h1>
        {onMetricMap && (
          <nav className="vl-seg" aria-label="sub-view">
            <button className="on" aria-current="page">
              Village
            </button>
            <button onClick={onMetricMap}>Metric map</button>
          </nav>
        )}
      </header>

      <div className="vl-hud vl-hud-tr" data-no-pick>
        <nav className="vl-seg" aria-label="source">
          {SOURCES.map((s) => (
            <button key={s.id} className={s.id === source ? "on" : ""} aria-pressed={s.id === source} title={s.hint} onClick={() => setSource(s.id)}>
              {s.label}
            </button>
          ))}
        </nav>
        <div className="vl-meta">
          <span>{tape ? tape.title : loadError ? `Could not load: ${loadError}` : source === "live" ? "Connecting…" : "Loading…"}</span>
          {state.simTs && (
            <b>
              {dayLabel(state.simTs)} {hhmm(state.simTs)}
            </b>
          )}
          {source === "live" && <span className={`vl-live ${live.state}`}>{live.state === "open" ? (live.agent ? "live · agent log" : "live · Stage-2 trail") : live.state}</span>}
        </div>
      </div>

      <div className="vl-hud vl-hud-bl" data-no-pick>
        <div className="vl-controls">
          <button onClick={() => player.setPlaying(!player.playing)} aria-label={player.playing ? "Pause" : "Play"}>
            {player.playing ? "❚❚" : "▶"}
          </button>
          <button
            onClick={() => {
              setDecision(null);
              player.seek(0);
              player.setPlaying(true);
            }}
            aria-label="Restart"
            title="Restart"
          >
            ↺
          </button>
          <button onClick={() => player.next()} aria-label="Next step" title="Next step">
            ⏭
          </button>
          <span className="vl-speeds" role="group" aria-label="speed">
            {SPEEDS.map((s) => (
              <button key={s} className={player.speed === s ? "on" : ""} onClick={() => player.setSpeed(s)}>
                {s}×
              </button>
            ))}
          </span>
        </div>
        <div className="vl-progress" aria-label="progress">
          <i style={{ width: `${(progress * 100).toFixed(1)}%` }} />
          <span>
            step {Math.max(0, state.index + 1)} of {player.timeline.slots.length}
            {player.timeline.waiting && !decision ? " · then your approval" : ""}
          </span>
        </div>
      </div>

      <div className="vl-hud vl-hud-bc" data-no-pick>
        <Caption state={state} />
      </div>

      {selected && <RolePanel role={selected} state={state} onClose={() => setSelected(null)} />}
      {approval && state.gate && (
        <ApprovalCard gate={state.gate} live={source === "live"} busy={deciding.busy} error={deciding.error} onDecide={decide} onClose={() => setApproval(false)} />
      )}
    </section>
  );
}
