import { describe, expect, it } from "vitest";
import { analysisURL, DEFAULT_QUERY, readAnalysisQuery, segmentKey } from "./query";

describe("analysis query links", () => {
  it("preserves presentation and style flags while replacing the workspace destination", () => {
    const segment = { provider: "PayCo & Co", country: "DE" };
    const query = { ...DEFAULT_QUERY, page: "metrics", metric: "payment_success_rate", segment, period: "30d" } as const;
    const url = analysisURL("https://argus.test/?fx=night&agentrun=run-10&view=incident&incident=INC-0001&receipt=r42", query);

    expect(readAnalysisQuery(url.search)).toEqual(query);
    expect(url.searchParams.get("view")).toBe("dashboard");
    expect(url.searchParams.get("agentrun")).toBe("run-10");
    expect(url.searchParams.get("fx")).toBe("night");
    expect(url.searchParams.has("incident")).toBe(false);
    expect(url.searchParams.has("receipt")).toBe(false);
    expect(url.searchParams.get("segment")).toBe(segmentKey({ country: "DE", provider: "PayCo & Co" }));
  });

  it("recovers from malformed query values and clears the analysis selection on exit", () => {
    expect(readAnalysisQuery("?analysis=metrics&segment=%7B%22DE%22%7D&period=unknown")).toEqual({ ...DEFAULT_QUERY, page: "metrics" });
    expect(readAnalysisQuery("?analysis=unknown")).toBeNull();
    const clean = analysisURL("https://argus.test/?view=dashboard&analysis=ads&metric=ctr&period=24h&fx=ice", null);
    expect(clean.search).toBe("?fx=ice");
  });

  it("keeps the Live Fix subject and recorded source in a shareable URL", () => {
    const query = { ...DEFAULT_QUERY, page: "live-fix", incidentId: "INC-0001", runId: "run:2" } as const;
    const url = analysisURL("https://argus.test/?view=incident&incident=INC-0001&agentrun=presentation-1", query);

    expect(readAnalysisQuery(url.search)).toEqual(query);
    expect(url.searchParams.get("agentrun")).toBe("presentation-1");
    expect(url.searchParams.has("incident")).toBe(false);
    const overview = analysisURL(url.href, DEFAULT_QUERY);
    expect(overview.searchParams.has("fixIncident")).toBe(false);
    expect(overview.searchParams.has("run")).toBe(false);
  });
});
