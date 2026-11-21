// The scene reads the style layer's tokens and falls back to the scene color table (report 2.2, I2).
import { describe, expect, it } from "vitest";
import { paletteHex } from "../../../src/fx/scene/palette";

describe("paletteHex", () => {
  it("uses the scene color table when no token is set (the lab page)", () => {
    const ice = paletteHex("ice");
    expect(ice.fog).toBe("#a2a8b5");
    expect(ice.stageHi).toBe("#c3c9d6");
    expect(ice.blockLit).toBe("#dfe4ee");
    expect(ice.glow.alarm).toBe("#f2585d");
    const night = paletteHex("night");
    expect(night.fog).toBe("#080d16");
    expect(night.rim).toBe("#bcd4ff");
    expect(night.snow).toEqual({ color: "#cfe0ff", alpha: 0.4 });
  });

  it("lets the layer's tokens win, ignoring empty ones", () => {
    const tokens: Record<string, string> = { "--fx-stage": " #112233 ", "--fx-glow-probe": "#00ff00", "--fx-hud": "" };
    const p = paletteHex("ice", (name) => tokens[name] ?? "");
    expect(p.fog).toBe("#112233");
    expect(p.glow.probe).toBe("#00ff00");
    expect(p.hud.color).toBe("#ffffff");
    expect(p.stageLo).toBe("#8a91a0");
  });
});
