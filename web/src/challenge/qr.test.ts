import { describe, expect, it } from "vitest";
import { encodeQr, formatBits, penalty, qrPath, reedSolomon, versionBits } from "./qr";

describe("QR encoder", () => {
  it("computes Reed-Solomon codewords (the 1-M HELLO WORLD example)", () => {
    const data = [32, 91, 11, 120, 209, 114, 220, 77, 67, 64, 236, 17, 236, 17, 236, 17];
    expect(reedSolomon(data, 10)).toEqual([196, 35, 39, 119, 235, 215, 231, 226, 93, 23]);
  });

  it("builds format and version information with their BCH codes", () => {
    // level M with mask 0, and level M with mask 4 (ISO/IEC 18004 Table C.1)
    expect(formatBits(0).toString(2).padStart(15, "0")).toBe("101010000010010");
    expect(formatBits(4).toString(2).padStart(15, "0")).toBe("100010111111001");
    // version 7 (ISO/IEC 18004 Table D.1)
    expect(versionBits(7).toString(2).padStart(18, "0")).toBe("000111110010010100");
  });

  it("picks the smallest version that holds the text", () => {
    expect(encodeQr("argus").version).toBe(1);
    const link = "http://192.168.178.23:8000/?challenge=verify&c=sha256:ee519191b65afd00566bdadd4997619933b28cbd58bc531a96634bf0e21a7a12";
    const code = encodeQr(link);
    expect(code.version).toBe(7);
    expect(code.size).toBe(45);
    expect(() => encodeQr("x".repeat(300))).toThrow(/too long/);
  });

  it("draws the three finder patterns and the timing lines", () => {
    const { dark, size } = encodeQr("https://example.org/?challenge=verify");
    const finder = (x0: number, y0: number) =>
      Array.from({ length: 7 }, (_, y) => Array.from({ length: 7 }, (_, x) => (dark[y0 + y][x0 + x] ? 1 : 0)).join("")).join("/");
    const expected = "1111111/1000001/1011101/1011101/1011101/1000001/1111111";
    expect(finder(0, 0)).toBe(expected);
    expect(finder(size - 7, 0)).toBe(expected);
    expect(finder(0, size - 7)).toBe(expected);
    for (let i = 8; i < size - 8; i++) {
      expect(dark[6][i]).toBe(i % 2 === 0);
      expect(dark[i][6]).toBe(i % 2 === 0);
    }
    expect(dark[size - 8][8]).toBe(true); // the dark module
  });

  it("is deterministic and keeps the lowest-penalty mask", () => {
    const a = encodeQr("sha256:ee519191");
    const b = encodeQr("sha256:ee519191");
    expect(a).toEqual(b);
    expect(penalty(a.dark)).toBeGreaterThan(0);
  });

  it("renders an SVG path with a quiet zone", () => {
    const code = encodeQr("a");
    expect(qrPath(code)).toMatch(/^M4 4h1v1h-1z/);
  });
});
