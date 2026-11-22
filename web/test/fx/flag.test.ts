// The style layer's switch (report section 3.3): off unless the address asks for it, never stored.
import { describe, expect, it } from "vitest";
import { FX_OFF, parseFx } from "../../src/fx/flag";

describe("parseFx", () => {
  it("is off without the parameter and for fx=0", () => {
    expect(parseFx("")).toEqual(FX_OFF);
    expect(parseFx("?demo=1&captions=1")).toEqual(FX_OFF);
    expect(parseFx("?fx=0")).toEqual(FX_OFF);
    expect(parseFx("?fx=")).toEqual(FX_OFF);
    expect(parseFx("?fx=disco")).toEqual(FX_OFF);
  });

  it("reads the two themes", () => {
    expect(parseFx("?fx=1").theme).toBe("ice");
    expect(parseFx("?fx=ice").theme).toBe("ice");
    expect(parseFx("?fx=ICE").theme).toBe("ice");
    expect(parseFx("?fx=night").theme).toBe("night");
  });

  it("combines with the demo options of the recording URL", () => {
    expect(parseFx("?demo=1&captions=1&fx=1")).toEqual({ theme: "ice", quality: "auto", intro: true, debug: false });
  });

  it("reads a fixed quality tier and falls back to auto", () => {
    expect(parseFx("?fx=1&fxq=low").quality).toBe("low");
    expect(parseFx("?fx=1&fxq=mid").quality).toBe("mid");
    expect(parseFx("?fx=1&fxq=high").quality).toBe("high");
    expect(parseFx("?fx=1&fxq=ultra").quality).toBe("auto");
    expect(parseFx("?fx=1").quality).toBe("auto");
  });

  it("skips the intro with fxintro=0 and plays it otherwise", () => {
    expect(parseFx("?fx=1&fxintro=0").intro).toBe(false);
    expect(parseFx("?fx=1&fxintro=off").intro).toBe(false);
    expect(parseFx("?fx=1&fxintro=1").intro).toBe(true);
    expect(parseFx("?fx=1").intro).toBe(true);
  });

  it("shows the debug readout only with fxdebug=1", () => {
    expect(parseFx("?fx=1&fxdebug=1").debug).toBe(true);
    expect(parseFx("?fx=1&fxdebug=yes").debug).toBe(false);
    expect(parseFx("?fxdebug=1").debug).toBe(false);
  });

  it("ignores the layer's other options while the layer is off", () => {
    expect(parseFx("?fxq=low&fxintro=0&fxdebug=1")).toEqual(FX_OFF);
  });
});
