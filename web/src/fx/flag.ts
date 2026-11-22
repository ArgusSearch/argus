// The style layer's switch. Read once from the address bar at start and never stored, so end-to-end tests and
// other tabs keep today's interface. Combines with the demo options: /?demo=1&captions=1&fx=1 is the
// recording URL.
//
//   fx=1 | fx=ice     Argus Ice, theme "ice"
//   fx=night          Argus Ice, theme "night"
//   fx=0 | absent     today's interface, nothing of the layer runs
//   fxq=low|mid|high  fixed quality tier for the scene (default auto)
//   fxintro=0         skip the loader hold and the intro (tests, repeated takes)
//   fxdebug=1         small readout of frame rate and scene quality in the bottom-left corner

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

/** Pure: the flags a query string asks for. Unknown values fall back to the defaults. */
export function parseFx(search: string): FxFlags {
  const params = new URLSearchParams(search);
  const theme = THEMES[(params.get("fx") ?? "").trim().toLowerCase()] ?? null;
  if (!theme) return FX_OFF;
  const asked = (params.get("fxq") ?? "").trim().toLowerCase();
  const quality = (QUALITIES as readonly string[]).includes(asked) ? (asked as FxQuality) : "auto";
  const intro = !NO.has((params.get("fxintro") ?? "").trim().toLowerCase());
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
