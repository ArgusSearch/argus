// The entry screen: the demo sign-in in front of Mission Control. A split card over the ice scene: on the left
// the night over the igloo, the Argus mark keeping watch and the seven agents on the snow; on the right who you
// enter as, what you are looking at (from GET /health) and one way in. There are no accounts in this demo and the
// screen says so; "Enter Mission Control" lands on the overview. EntryGate.tsx and gate.ts decide when it shows.

import { useEffect, useRef, useState } from "react";
import { api } from "../../lib/api";
import { staticReplay } from "../../lib/deployment";
import { dayLabel, hhmm } from "../../lib/format";
import type { Health } from "../../lib/types";
import { AgentAvatar, type RoleId } from "../../village/avatars";
import { useFx } from "../StyleProvider";
import { CornerHud } from "../ui/CornerHud";
import { FacetMark, Wordmark } from "./brand";
import "./entry.css";

/**
 * The crew in front of the igloo, left to right in the order a case travels. Each avatar is painted once and bobs
 * on the compositor: live painters (canvas shadows every frame) cost the scene behind its frame rate.
 */
const CREW: readonly RoleId[] = ["watcher", "cartographer", "detective", "market", "skeptic", "narrator", "operator"];

/** Keys the entry keeps from the page behind it (the view host's 1 to 5, the Ask panel's /). */
const PASS_THROUGH = new Set(["Tab", "Enter", " ", "Escape", "Shift"]);

/** The entry screen itself; EntryGate.tsx decides when it shows and loads this module only then. */
export default function EntryPage({ leaving, onEnter }: { leaving: boolean; onEnter: () => void }) {
  const { phase } = useFx();
  const [health, setHealth] = useState<Health | null>();
  const dialog = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (staticReplay) return;
    let live = true;
    api.health().then(
      (h) => live && setHealth(h),
      () => live && setHealth(null),
    );
    return () => {
      live = false;
    };
  }, []);

  // the page behind keeps its shortcuts to itself while the entry is up; Enter anywhere on the card enters
  useEffect(() => {
    const hold = (event: KeyboardEvent) => {
      const target = event.target as HTMLElement | null;
      if (event.key === "Enter" && !target?.closest("a, button")) {
        event.preventDefault();
        event.stopImmediatePropagation();
        onEnter();
        return;
      }
      if (!PASS_THROUGH.has(event.key) && !event.metaKey && !event.ctrlKey) event.stopImmediatePropagation();
    };
    window.addEventListener("keydown", hold, true);
    return () => window.removeEventListener("keydown", hold, true);
  }, [onEnter]);

  // the dialog takes focus once the loader has lifted (no ring: the button gets one only when tabbed to)
  const shown = phase !== "boot";
  useEffect(() => {
    if (shown) dialog.current?.focus({ preventScroll: true });
  }, [shown]);

  const recorded = health?.mode !== "live";
  const lastCheck = health?.sim_ts ? `${dayLabel(health.sim_ts)} · ${hhmm(health.sim_ts)}` : null;
  const checkStatus = health === null ? "Connection unavailable" : "Connecting…";

  return (
    <div
      ref={dialog}
      tabIndex={-1}
      className={`fx-entry${shown ? " shown" : ""}${leaving ? " leaving" : ""}`}
      role="dialog"
      aria-modal="true"
      aria-labelledby="fx-entry-title"
      aria-describedby="fx-entry-lede"
    >
      <CornerHud fixed tl={<span className="fx-hud">Argus</span>} tr="Mission control" bl="Demo sign-in" br="Autonomous watch" />
      <div className="fx-entry-card">
        <section className="fx-entry-art" aria-label="Argus keeps watch">
          <EntrySky />
          <Wordmark className="fx-entry-wordmark" />
          <div className="fx-entry-mark" aria-hidden="true">
            <span className="fx-entry-disc" />
            <FacetMark tone="tinted" className="fx-entry-facet" />
          </div>
          <EntryIgloo />
          <ul className="fx-entry-crew" aria-label="the seven agents">
            {CREW.map((role) => (
              <li key={role}>
                <AgentAvatar role={role} size={52} badge={false} paused />
              </li>
            ))}
          </ul>
          <p className="fx-entry-caption">Seven agents keep watch through the night. You decide what they do.</p>
        </section>

        <section className="fx-entry-form">
          <h1 id="fx-entry-title">Welcome to Mission Control</h1>
          <p id="fx-entry-lede" className="fx-entry-lede">
            {staticReplay
              ? "See what Argus found in a sealed investigation of a simulated shop."
              : "Argus checks your shop's key numbers every hour, explains every change it finds, and asks you before it acts."}
          </p>

          <dl className="fx-entry-who">
            <div>
              <dt>You enter as</dt>
              <dd>
                <span className="fx-entry-monogram" aria-hidden="true">
                  DO
                </span>
                <span>Demo operator</span>
                <em>demo</em>
              </dd>
            </div>
            <div>
              <dt>Shop</dt>
              <dd>
                <span>A simulated online shop</span>
                <em>test data</em>
              </dd>
            </div>
            <div>
              <dt>{staticReplay ? "Mode" : "Last check"}</dt>
              <dd>
                <i className={`fx-entry-dot${health ? " on" : ""}`} aria-hidden="true" />
                <span>{staticReplay ? "Recorded demo" : lastCheck ?? (health ? "Waiting for the first check" : checkStatus)}</span>
                {health && <em>{recorded ? "recorded run" : "live"}</em>}
              </dd>
            </div>
          </dl>

          <button type="button" className="fx-entry-go" onClick={onEnter} disabled={leaving}>
            <span>{staticReplay ? "Open the sealed replay" : "Enter Mission Control"}</span>
            <svg viewBox="0 0 16 16" aria-hidden="true">
              <path d="M3 8h9.5M8.5 4l4 4-4 4" />
            </svg>
          </button>
          {staticReplay ? (
            <a className="fx-entry-alt" href="/?view=settings&tab=quiet-hours">Settings</a>
          ) : (
            <>
              <a className="fx-entry-alt" href="/?demo=1&captions=1&fx=1">
                Or watch the guided demo: one incident, start to finish
              </a>
              <p className="fx-entry-foot">
                This demo has no accounts or passwords. Approvals go through a local operator session on this machine.
              </p>
            </>
          )}
        </section>
      </div>
    </div>
  );
}

/** The sky: a horizon arc (violet, white-hot apex, green) and a few stars. Hand-drawn SVG, decoration only. */
function EntrySky() {
  return (
    <svg className="fx-entry-sky" viewBox="0 0 560 300" preserveAspectRatio="xMidYMin slice" aria-hidden="true">
      <defs>
        <linearGradient id="fx-entry-arc" x1="0" x2="1" y1="0" y2="0">
          <stop offset="0" stopColor="#3a2760" stopOpacity="0" />
          <stop offset="0.18" stopColor="#8d67c4" />
          <stop offset="0.34" stopColor="#dda6f3" />
          <stop offset="0.5" stopColor="#fff5ff" />
          <stop offset="0.66" stopColor="#b7ccc3" />
          <stop offset="0.82" stopColor="#4ac499" />
          <stop offset="1" stopColor="#1a553f" stopOpacity="0" />
        </linearGradient>
        <filter id="fx-entry-blur" x="-20%" y="-60%" width="140%" height="220%">
          <feGaussianBlur stdDeviation="10" />
        </filter>
      </defs>
      <g className="fx-entry-arc">
        <path d="M-60 190 Q280 0 620 190" stroke="url(#fx-entry-arc)" strokeWidth="22" fill="none" opacity="0.45" filter="url(#fx-entry-blur)" />
        <path d="M-60 190 Q280 0 620 190" stroke="url(#fx-entry-arc)" strokeWidth="1.6" fill="none" />
      </g>
      <g fill="#fff5ff">
        {STARS.map(([x, y, r]) => (
          <circle key={`${x}-${y}`} cx={x} cy={y} r={r} opacity={r > 1 ? 0.9 : 0.55} />
        ))}
      </g>
    </svg>
  );
}

const STARS: readonly [number, number, number][] = [
  [52, 64, 1.2],
  [118, 132, 0.8],
  [190, 46, 0.9],
  [372, 38, 0.8],
  [440, 112, 1.2],
  [508, 58, 0.8],
  [78, 214, 0.7],
  [492, 220, 0.7],
  [300, 70, 0.6],
];

/** An igloo of ice blocks whose doorway glows like the mark's core. Hand-drawn SVG, decoration only. */
function EntryIgloo() {
  const rows = [0, 1, 2, 3, 4];
  const base = 132;
  const course = 22;
  return (
    <svg className="fx-entry-igloo" viewBox="0 0 300 140" aria-hidden="true">
      <defs>
        <linearGradient id="fx-entry-ice" x1="0" x2="0" y1="0" y2="1">
          <stop offset="0" stopColor="#f3f1fd" stopOpacity="0.96" />
          <stop offset="1" stopColor="#a9aed0" stopOpacity="0.9" />
        </linearGradient>
        <radialGradient id="fx-entry-door" cx="0.5" cy="1" r="0.95">
          <stop offset="0" stopColor="#fff5ff" />
          <stop offset="0.4" stopColor="#c9a0ff" />
          <stop offset="1" stopColor="#893eee" stopOpacity="0.35" />
        </radialGradient>
        <clipPath id="fx-entry-dome">
          <path d={`M20 ${base} A130 120 0 0 1 280 ${base} Z`} />
        </clipPath>
      </defs>
      <path d={`M20 ${base} A130 120 0 0 1 280 ${base} Z`} fill="url(#fx-entry-ice)" />
      <g clipPath="url(#fx-entry-dome)" stroke="#555a82" strokeOpacity="0.42" strokeWidth="1.1" fill="none">
        {rows.map((i) => (
          <line key={`r${i}`} x1="0" x2="300" y1={base - (i + 1) * course} y2={base - (i + 1) * course} />
        ))}
        {rows.flatMap((i) =>
          Array.from({ length: 8 }, (_, j) => {
            const x = 30 + (i % 2 ? 18 : 0) + j * 36;
            const top = base - (i + 1) * course;
            return <line key={`j${i}-${j}`} x1={x} x2={x} y1={top} y2={top + course} />;
          }),
        )}
      </g>
      <path d={`M114 ${base} V104 A36 32 0 0 1 186 104 V${base} Z`} fill="#16112c" />
      <path className="fx-entry-door" d={`M122 ${base} V106 A28 26 0 0 1 178 106 V${base} Z`} fill="url(#fx-entry-door)" />
      <path d={`M0 ${base + 0.5} H300`} stroke="#e9e0fb" strokeOpacity="0.3" />
    </svg>
  );
}
