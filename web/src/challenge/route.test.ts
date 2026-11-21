import { describe, expect, it } from "vitest";
import { isLoopback, parseRoute, phoneLink, routeHref } from "./route";

describe("challenge routes", () => {
  it("ignores URLs without ?challenge", () => {
    expect(parseRoute("")).toBeNull();
    expect(parseRoute("?demo=1")).toBeNull();
  });

  it("reads the screen, defaulting to the big-screen start", () => {
    expect(parseRoute("?challenge")?.screen).toBe("pick");
    expect(parseRoute("?challenge=1")?.screen).toBe("pick");
    expect(parseRoute("?challenge=VERIFY&c=abc&lan=10.0.0.2:8000")).toEqual({ screen: "verify", commitment: "abc", lan: "10.0.0.2:8000" });
  });

  it("switches screens and keeps other parameters", () => {
    expect(routeHref("?demo=1&challenge=pick", "run")).toBe("?demo=1&challenge=run");
    expect(routeHref("?challenge=run", null)).toBe("?");
    expect(routeHref("?challenge", "reveal", { lan: "10.0.0.2:8000" })).toBe("?challenge=reveal&lan=10.0.0.2%3A8000");
    expect(routeHref("?challenge=pick&lan=x", "pick", { lan: null })).toBe("?challenge=pick");
  });

  it("knows which hosts a phone cannot reach", () => {
    expect(isLoopback("127.0.0.1:8000")).toBe(true);
    expect(isLoopback("localhost:5173")).toBe(true);
    expect(isLoopback("[::1]:8000")).toBe(true);
    expect(isLoopback("192.168.1.20:8000")).toBe(false);
  });

  it("builds the phone link from the LAN address when one is given", () => {
    const c = "sha256:ee519191";
    expect(phoneLink("http://127.0.0.1:8000", null, c)).toBe("http://127.0.0.1:8000/?challenge=verify&c=ee519191");
    expect(phoneLink("http://127.0.0.1:8000", "192.168.1.20:8000/", c)).toBe("http://192.168.1.20:8000/?challenge=verify&c=ee519191");
    expect(phoneLink("http://x", "https://argus.local", c)).toBe("https://argus.local/?challenge=verify&c=ee519191");
  });
});
