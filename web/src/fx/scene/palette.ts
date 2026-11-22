// Scene colors. The style layer's tokens win (report section 3.4, I2); the defaults of the scene color table
// (section 2.2) fill in when a token is empty, for example on the lab page.

import { Color } from "three";

export type SceneTheme = "ice" | "night";

interface Swatch {
  color: string;
  alpha: number;
}

export interface PaletteHex {
  theme: SceneTheme;
  fog: string;
  stageHi: string;
  stageLo: string;
  ground: string;
  blockLit: string;
  blockShade: string;
  rim: string;
  hud: Swatch;
  snow: Swatch;
  shadow: Swatch;
  glow: { ice: string; ok: string; watch: string; alarm: string; probe: string; calm: string };
  edge: { valid: Swatch; supported: Swatch; probation: Swatch; proposed: Swatch; broken: Swatch; definition: Swatch };
  /** luminance (linear) above which a pixel feeds the bloom */
  bloomThreshold: number;
  bloomStrength: number;
}

const DEFAULTS: Record<SceneTheme, PaletteHex> = {
  ice: {
    theme: "ice",
    fog: "#a2a8b5",
    stageHi: "#c3c9d6",
    stageLo: "#8a91a0",
    ground: "#9aa1af",
    blockLit: "#dfe4ee",
    blockShade: "#6b7385",
    rim: "#ffffff",
    hud: { color: "#ffffff", alpha: 0.9 },
    snow: { color: "#ffffff", alpha: 0.55 },
    shadow: { color: "#596173", alpha: 0.42 },
    glow: { ice: "#d6e6ff", ok: "#3fbf8f", watch: "#e3a63b", alarm: "#f2585d", probe: "#5aa7ff", calm: "#9d8cff" },
    edge: {
      valid: { color: "#ffffff", alpha: 0.78 },
      supported: { color: "#ece8ff", alpha: 0.85 },
      probation: { color: "#e3a63b", alpha: 0.95 },
      proposed: { color: "#ffffff", alpha: 0.45 },
      broken: { color: "#f2585d", alpha: 1 },
      definition: { color: "#ffffff", alpha: 0.38 },
    },
    bloomThreshold: 0.92,
    bloomStrength: 0.7,
  },
  night: {
    theme: "night",
    fog: "#080d16",
    stageHi: "#16223a",
    stageLo: "#05080e",
    ground: "#101a2d",
    blockLit: "#33415e",
    blockShade: "#0d1422",
    rim: "#bcd4ff",
    hud: { color: "#ffffff", alpha: 0.8 },
    snow: { color: "#cfe0ff", alpha: 0.4 },
    shadow: { color: "#000000", alpha: 0.5 },
    glow: { ice: "#d6e6ff", ok: "#3fbf8f", watch: "#e3a63b", alarm: "#f2585d", probe: "#5aa7ff", calm: "#9d8cff" },
    edge: {
      valid: { color: "#8d9bbd", alpha: 0.75 },
      supported: { color: "#9a94e0", alpha: 0.85 },
      probation: { color: "#e3a63b", alpha: 0.95 },
      proposed: { color: "#56617a", alpha: 0.8 },
      broken: { color: "#f2585d", alpha: 1 },
      definition: { color: "#3f4b66", alpha: 0.9 },
    },
    bloomThreshold: 0.32,
    bloomStrength: 0.75,
  },
};

/** Pure: the palette of a theme, with the tokens `read` returns (empty string when unset) layered on top. */
export function paletteHex(theme: SceneTheme, read: (name: string) => string = () => ""): PaletteHex {
  const base = DEFAULTS[theme];
  const token = (name: string, fallback: string) => read(name).trim() || fallback;
  const hud = token("--fx-hud", base.hud.color);
  return {
    ...base,
    fog: token("--fx-stage", base.fog),
    stageHi: token("--fx-stage-hi", base.stageHi),
    stageLo: token("--fx-stage-lo", base.stageLo),
    hud: { ...base.hud, color: hud },
    glow: {
      ice: token("--fx-glow-ice", base.glow.ice),
      ok: token("--fx-glow-ok", base.glow.ok),
      watch: token("--fx-glow-watch", base.glow.watch),
      alarm: token("--fx-glow-alarm", base.glow.alarm),
      probe: token("--fx-glow-probe", base.glow.probe),
      calm: token("--fx-glow-calm", base.glow.calm),
    },
  };
}

/** The theme `<html data-fx>` asks for; ice when the attribute is absent or unknown. */
export function themeOf(root: HTMLElement): SceneTheme {
  return root.dataset.fx === "night" ? "night" : "ice";
}

export function readPaletteHex(): PaletteHex {
  const root = document.documentElement;
  const style = getComputedStyle(root);
  return paletteHex(themeOf(root), (name) => style.getPropertyValue(name));
}

/** A parsed color that tolerates anything CSS accepts but Three.js does not (it then keeps the fallback). */
export function color(value: string, fallback = "#ffffff"): Color {
  const c = new Color(fallback);
  try {
    c.setStyle(value);
  } catch {
    /* keep the fallback */
  }
  return c;
}
