// The style layer's switch. Argus Ice is the interface: a page load without options gets it. The classic
// interface (the dark one before the layer, where the teammates' screens also live) is one option away.
// Read once from the address bar at start and never stored. The recording URL /?demo=1&captions=1&fx=1 keeps
// working unchanged.
//
//   absent | fx=1 | fx=ice   Argus Ice, theme "ice"
//   fx=night                 Argus Ice, theme "night"
//   classic=1 | fx=0         the classic interface, nothing of the layer runs
//   fxq=low|mid|high         fixed quality tier for the scene (default auto)
//   fxintro=0                skip the loader hold and the intro (tests, repeated takes)
//   fxdebug=1                small readout of frame rate and scene quality in the bottom-left corner

export type FxTheme = "ice" | "night";
export type FxQuality = "auto" | "low" | "mid" | "high";

export interface FxFlags {
  /** The theme, or null when the layer is off. */
  theme: FxTheme | null;
  quality: FxQuality;
  /** Play the loader and the intro choreography. */
  intro: boolean;
  debug: boolean;
}

export const FX_OFF: FxFlags = Object.freeze({ theme: null, quality: "auto", intro: true, debug: false });

const THEMES: Record<string, FxTheme> = { "1": "ice", ice: "ice", night: "night" };
const QUALITIES: readonly FxQuality[] = ["auto", "low", "mid", "high"];
const NO = new Set(["0", "false", "off", "no"]);

const read = (params: URLSearchParams, key: string) => (params.get(key) ?? "").trim().toLowerCase();

/** Pure: the flags a query string asks for. Unknown values fall back to the defaults (Argus Ice). */
export function parseFx(search: string): FxFlags {
  const params = new URLSearchParams(search);
  const fx = read(params, "fx");
  // ?classic or ?classic=1 (not ?classic=0) and the old explicit fx=0 ask for the classic interface
  if ((params.has("classic") && !NO.has(read(params, "classic"))) || NO.has(fx)) return FX_OFF;
  const theme = THEMES[fx] ?? "ice";
  const asked = read(params, "fxq");
  const quality = (QUALITIES as readonly string[]).includes(asked) ? (asked as FxQuality) : "auto";
  const intro = !NO.has(read(params, "fxintro"));
  const debug = (params.get("fxdebug") ?? "").trim() === "1";
  return { theme, quality, intro, debug };
}

let cached: FxFlags | null = null;

/** The flags of this page load, read once from window.location. */
export function fxFlags(): FxFlags {
  if (!cached) cached = typeof window === "undefined" ? FX_OFF : parseFx(window.location.search);
  return cached;
}

/** True when the layer is on for this page load. */
export function fxOn(): boolean {
  return fxFlags().theme !== null;
}
