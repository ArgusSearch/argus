// Reads the recorded demo pack (fixtures/graph_extension/placements.json, the API's PlacementResult list) the way
// the "New metric placed" card does: the exact chain, the ambiguous yield with its two parents, the fan-out.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { placedNodeStyles } from "../../src/graph-extension/GraphExtensionLayer";
import { evidenceOf, nextOfPack, placedNodes, placementView } from "../../src/graph-extension/model";
import type { PlacementResult } from "../../src/graph-extension/types";

const placements: PlacementResult[] = JSON.parse(
  readFileSync(fileURLToPath(new URL("../../../fixtures/graph_extension/placements.json", import.meta.url)), "utf8"),
);
const byName = (name: string) => placements.find((p) => p.metric.name === name)!;

describe("placement card model", () => {
  it("reads an exact placement as its lineage chain", () => {
    const v = placementView(byName("cost_per_impression"));
    expect([v.verdict, v.tone, v.kind]).toEqual(["EXACT", "good", "New metric placed"]);
    expect(v.routes).toHaveLength(1);
    expect(v.routes[0]).toMatchObject({ sources: ["ctr", "cpc"], status: "VALID" });
    expect(v.headline).toBe("Cost per impression = CTR × CPC, proven on the data (residual 0.00 % over 672 h).");
    expect(v.feeds.map((f) => f.target)).toEqual(["ad_spend"]);
    expect(v.dims).toEqual(["advertiser_id", "country", "platform"]);
    expect(v.receipts).toBeGreaterThan(0);
  });

  it("shows both parents of the ambiguous metric, the chosen one first and on probation", () => {
    const v = placementView(byName("revenue_per_impression"));
    expect([v.verdict, v.tone]).toEqual(["AMBIGUOUS", "watch"]);
    expect(v.routes.map((r) => [r.sources.join("*"), r.status])).toEqual([
      ["cost_per_impression*roas", "PROBATION"],
      ["conversions_per_impression*revenue_per_conversion", "ALTERNATIVE"],
    ]);
    expect(v.headline).toContain("Two parents fit equally well");
    expect(v.reasons.some((r) => r.startsWith("ambiguous: 2 equally simple formulas fit"))).toBe(true);
  });

  it("explains a fan-out rejection with its factor", () => {
    const p = byName("ad_spend_per_session");
    const v = placementView(p);
    expect([v.verdict, v.tone, v.kind]).toEqual(["REJECTED", "bad", "Metric rejected"]);
    expect(v.headline).toBe("Not placed: the join counts rows 6.72 times over. A repaired query is attached.");
    expect(p.repair?.diff).toContain("+WITH num AS");
    expect(v.reasons.filter((r) => r.startsWith("fan-out guard"))).toHaveLength(2);
  });

  it("knows the placed nodes, the next pack metric and how to highlight them", () => {
    expect(placedNodes(placements)).toEqual([
      "cost_per_impression",
      "conversions_per_impression",
      "revenue_per_conversion",
      "revenue_per_impression",
    ]);
    const recorded = placements.map((p) => p.metric);
    expect(nextOfPack({ placements: placements.slice(0, 2), recorded })?.name).toBe("revenue_per_conversion");
    expect(nextOfPack({ placements, recorded })).toBeNull();
    const css = placedNodeStyles(["cost_per_impression", "revenue_per_impression"]);
    expect(css).toContain('.react-flow__node[data-id="revenue_per_impression"] .mnode { animation: gx-arrive');
    expect(css).toContain('[data-node="cost_per_impression"]');
    expect(placedNodeStyles([])).toBe("");
    expect(evidenceOf(null)).toBe("not tested here");
  });
});
