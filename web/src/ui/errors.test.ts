import { describe, expect, it } from "vitest";
import { ApiError } from "../lib/api";
import { explainError } from "./errors";

describe("explainError", () => {
  it("names the replay 409 on a re-run in plain English", () => {
    const e = explainError(new ApiError(409, "re-runs need a world"), "/receipts/r12/rerun");
    expect(e.title).toBe("Receipt re-runs need live mode");
    expect(e.detail).toContain("make demo");
    expect(e.retry).toBe(false);
  });

  it("explains a network failure without the browser's wording", () => {
    const e = explainError(new TypeError("Failed to fetch"), "/graph");
    expect(e.title).toBe("Can't reach the Argus API");
    expect(e.detail).toContain("make api");
    expect(e.retry).toBe(true);
  });

  it("calls a 501 stub not built yet and does not offer a retry", () => {
    const e = explainError(new ApiError(501, "not built yet"), "/challenge/commit");
    expect(e).toEqual({ title: "Not built yet", detail: "The API does not serve /challenge/commit yet.", retry: false });
  });

  it("never shows raw JSON from the server", () => {
    const e = explainError(new ApiError(422, '[{"loc":["body"],"msg":"field required"}]'), "/replay");
    expect(e.detail).not.toContain("{");
    expect(e.detail).not.toContain("[");
    const obj = explainError(new ApiError(404, "[object Object]"), "/incidents/INC-9");
    expect(obj.detail).not.toContain("object");
    expect(obj.detail).toContain("/incidents/INC-9");
  });

  it("keeps a readable server message and ends it with a full stop", () => {
    expect(explainError(new ApiError(404, "no receipt r999"), "/receipts/r999").detail).toBe("no receipt r999.");
  });

  it("reads the bare status that api.report throws", () => {
    expect(explainError(new Error("503"), "/incidents/INC-0001/report").title).toBe("The API hit an error");
  });

  it("falls back for unknown errors", () => {
    expect(explainError("boom").title).toBe("Something went wrong");
  });
});
