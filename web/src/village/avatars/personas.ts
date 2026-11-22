// The seven agent personas: a plush bot body (bot-avatars, MIT) in the role's color, our own slim tech armor,
// a job-specific HUD detail and an acronym nameplate. Names are our own; none is a film character's.
// `name` is the chosen acronym; `names` lists the candidates the captain picks from (the first is the default).

import type { BotAvatarType } from "bot-avatars";
import type { RoleId } from "../roles";

export type HudDetail = "scan" | "reticle" | "scale" | "bars" | "page" | "power" | "graph";

export interface AcronymOption {
  /** dotted acronym, e.g. "S.L.E.U.T.H." */
  acronym: string;
  /** what the letters stand for */
  meaning: string;
}

export interface Persona {
  role: RoleId;
  /** the job title the village shows under the name */
  title: string;
  names: [AcronymOption, AcronymOption];
  body: BotAvatarType;
  /** plush fur color */
  fur: string;
  /** armor seams, HUD ring and glow */
  glow: string;
  detail: HudDetail;
  personality: string;
  voice: string;
  ability: string;
  /** a typical status line, as the village shows it */
  status: string;
}

export const PERSONAS: Readonly<Record<RoleId, Persona>> = {
  watcher: {
    role: "watcher",
    title: "Watcher",
    names: [
      { acronym: "B.E.A.C.O.N.", meaning: "Bands, Expectations And Charts, Overnight, Non-stop" },
      { acronym: "O.W.L.", meaning: "Overnight Watch on Levels" },
    ],
    body: "ghost",
    fur: "#f4f2fa",
    glow: "#7cc4ff",
    detail: "scan",
    personality: "Calm night owl, never blinks first; speaks only when a number leaves its band.",
    voice: "Quiet, measured, short sentences.",
    ability: "Scores every metric every simulated hour; a scanning beam sweeps its visor.",
    status: "Hour 18:00 · 27 metrics inside their bands",
  },
  detective: {
    role: "detective",
    title: "Detective",
    names: [
      { acronym: "S.L.E.U.T.H.", meaning: "Segment Locator, Event Unmasker, Timeline Hunter" },
      { acronym: "T.R.A.C.E.", meaning: "Tracks Root-cause Across Charts and Events" },
    ],
    body: "clover",
    fur: "#41c4ff",
    glow: "#9fd0ff",
    detail: "reticle",
    personality: "Curious and quick, a little theatrical; loves the moment the segment clicks.",
    voice: "Brisk, thinks out loud in questions.",
    ability: "Drills a drop down to the exact segment and hour; a targeting reticle over one eye.",
    status: "Narrowed it to DE · android · PayCo",
  },
  skeptic: {
    role: "skeptic",
    title: "Skeptic",
    names: [
      { acronym: "D.O.U.B.T.", meaning: "Disproves Obvious, Unfounded Beliefs by Testing" },
      { acronym: "N.U.L.L.", meaning: "Null-hypothesis Upholder, Lets nothing Lie" },
    ],
    body: "square",
    fur: "#ff8a70",
    glow: "#ffb39f",
    detail: "scale",
    personality: "Dry, polite contrarian; happiest when a suspect turns out innocent.",
    voice: "Deadpan, precise, the occasional 'prove it'.",
    ability: "Holdouts and placebo weeks rule out false trails; a holo balance floats beside it.",
    status: "Ruled out: android-app 8.3.0",
  },
  market: {
    role: "market",
    title: "Market Analyst",
    names: [
      { acronym: "T.I.C.K.E.R.", meaning: "Tracks Index Comparisons, Keeps Expectations Real" },
      { acronym: "P.E.E.R.", meaning: "Peer Economy Exposure Reader" },
    ],
    body: "flower",
    fur: "#2fcb7a",
    glow: "#8ff0c4",
    detail: "bars",
    personality: "Upbeat, big-picture, always asks what everyone else saw.",
    voice: "Friendly, quick, numbers-first.",
    ability: "Holds the shop against a market index so a shared downturn is not filed as ours.",
    status: "Market flat: this one is ours",
  },
  narrator: {
    role: "narrator",
    title: "Narrator",
    names: [
      { acronym: "S.C.R.I.B.E.", meaning: "Summarises Cases, Receipts In Brief English" },
      { acronym: "F.O.L.I.O.", meaning: "Files Our Learnings Into Orderly reports" },
    ],
    body: "star",
    fur: "#ffe27a",
    glow: "#ffe08a",
    detail: "page",
    personality: "Warm and concise; never states a number without its receipt.",
    voice: "Clear, calm, plain English, morning-news cadence.",
    ability: "Writes the verdict and the morning report; a holo page fills line by line.",
    status: "INC-0001 filed with 4 receipts",
  },
  operator: {
    role: "operator",
    title: "Operator",
    names: [
      { acronym: "L.E.V.E.R.", meaning: "Locked Execution, Verified Effect, Reversible" },
      { acronym: "H.A.N.D.S.", meaning: "Human-Approved, Never Decides Solo" },
    ],
    body: "pill",
    fur: "#3dd6c4",
    glow: "#8ff5e6",
    detail: "power",
    personality: "Careful, deferential, safety-first; asks before touching anything.",
    voice: "Steady and formal, confirms every step back to you.",
    ability: "Acts only after your approval, then checks the effect against an untouched twin.",
    status: "Waiting for your approval",
  },
  cartographer: {
    role: "cartographer",
    title: "Cartographer",
    names: [
      { acronym: "G.R.I.D.", meaning: "Graph Relations, Identities and Derivations" },
      { acronym: "C.O.M.P.A.S.S.", meaning: "Charts Our Metric Paths And Splits Sums" },
    ],
    body: "hexagon",
    fur: "#b7a8ff",
    glow: "#d2c9ff",
    detail: "graph",
    personality: "Methodical and tidy; every edge tested, every formula drawn.",
    voice: "Patient, exact, likes the word 'holds'.",
    ability: "Tests every formula edge and walks a metric down its formula; a holo graph orbits it.",
    status: "34 of 34 formula edges hold",
  },
};

/** The acronym the product shows for a role (the first candidate until the captain picks). */
export function agentName(role: RoleId): string {
  return PERSONAS[role].names[0].acronym;
}
