import { describe, expect, it } from "vitest";
import { verdictLabel } from "../src/lib/format";

describe("verdictLabel (#15)", () => {
  it("writes every verdict with spaces", () => {
    expect(verdictLabel("SUPPORTED_CAUSE")).toBe("SUPPORTED CAUSE");
    expect(verdictLabel("DATA_ISSUE")).toBe("DATA ISSUE");
    expect(verdictLabel("EXPECTED")).toBe("EXPECTED");
  });
  it("leaves other step results alone", () => {
    expect(verdictLabel("android / DE / PayCo explains 100%")).toBe("android / DE / PayCo explains 100%");
    expect(verdictLabel("NOT_A_VERDICT")).toBe("NOT_A_VERDICT");
  });
});
