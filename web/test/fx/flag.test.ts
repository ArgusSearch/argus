// The style layer's switch: Argus Ice by default, the classic interface with ?classic=1 (or the old fx=0).
import { describe, expect, it } from "vitest";
import { FX_OFF, parseFx } from "../../src/fx/flag";

const ICE = { theme: "ice", quality: "auto", intro: true, debug: false };

describe("parseFx", () => {
  it("is Argus Ice without options and for unknown values", () => {
    expect(parseFx("")).toEqual(ICE);
    expect(parseFx("?")).toEqual(ICE);
    expect(parseFx("?demo=1&captions=1")).toEqual(ICE);
    expect(parseFx("?fx=")).toEqual(ICE);
    expect(parseFx("?fx=disco")).toEqual(ICE);
    expect(parseFx("?view=incident&incident=INC-0001")).toEqual(ICE);
  });

  it("is the classic interface with ?classic and with the old fx=0", () => {
    expect(parseFx("?classic=1")).toEqual(FX_OFF);
    expect(parseFx("?classic")).toEqual(FX_OFF);
    expect(parseFx("?classic=true&demo=1")).toEqual(FX_OFF);
    expect(parseFx("?classic=1&fx=1")).toEqual(FX_OFF);
    expect(parseFx("?fx=0")).toEqual(FX_OFF);
    expect(parseFx("?fx=off")).toEqual(FX_OFF);
    expect(parseFx("?classic=0")).toEqual(ICE);
  });

  it("reads the two themes", () => {
    expect(parseFx("?fx=1").theme).toBe("ice");
    expect(parseFx("?fx=ice").theme).toBe("ice");
    expect(parseFx("?fx=ICE").theme).toBe("ice");
    expect(parseFx("?fx=night").theme).toBe("night");
  });

  it("keeps the recording URL as it was", () => {
    expect(parseFx("?demo=1&captions=1&fx=1")).toEqual(ICE);
  });

  it("reads a fixed quality tier and falls back to auto", () => {
    expect(parseFx("?fx=1&fxq=low").quality).toBe("low");
    expect(parseFx("?fxq=mid").quality).toBe("mid");
    expect(parseFx("?fx=1&fxq=high").quality).toBe("high");
    expect(parseFx("?fx=1&fxq=ultra").quality).toBe("auto");
    expect(parseFx("?fx=1").quality).toBe("auto");
  });

  it("skips the intro with fxintro=0 and plays it otherwise", () => {
    expect(parseFx("?fx=1&fxintro=0").intro).toBe(false);
    expect(parseFx("?fxintro=off").intro).toBe(false);
    expect(parseFx("?fx=1&fxintro=1").intro).toBe(true);
    expect(parseFx("?fx=1").intro).toBe(true);
  });

  it("shows the debug readout only with fxdebug=1", () => {
    expect(parseFx("?fx=1&fxdebug=1").debug).toBe(true);
    expect(parseFx("?fxdebug=1").debug).toBe(true);
    expect(parseFx("?fx=1&fxdebug=yes").debug).toBe(false);
  });

  it("ignores the layer's options in the classic interface", () => {
    expect(parseFx("?classic=1&fxq=low&fxintro=0&fxdebug=1")).toEqual(FX_OFF);
  });
});
