// The metric tree built from the recorded seed graph (fixtures/graph.json: 27 metrics, 44 edges, 4 logs).
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import type { Graph } from "../../src/lib/types";
import { buildTree, countMetrics, flatten, openPathTo } from "../../src/views/tree";

const graph: Graph = JSON.parse(readFileSync(fileURLToPath(new URL("../../../fixtures/graph.json", import.meta.url)), "utf8"));

describe("buildTree", () => {
  const tree = buildTree(graph);
  const all = [...tree.roots, ...tree.unattached];

  it("reads the fixture it was written for", () => {
    expect(graph.nodes).toHaveLength(27);
    expect(graph.edges).toHaveLength(44);
    expect(graph.logs).toHaveLength(4);
  });

  it("starts at north-star metrics", () => {
    expect(tree.roots.length).toBeGreaterThan(0);
    const stars = new Set(graph.nodes.filter((n) => n.north_star).map((n) => n.id));
    for (const root of tree.roots) expect(stars.has(root.id)).toBe(true);
    expect(tree.roots.map((r) => r.id)).toContain("gmv");
  });

  it("expands every metric exactly once: under a north star or listed as unattached", () => {
    const homes = flatten(all).filter((r) => r.kind === "metric" && !r.ref);
    expect(homes.map((r) => r.id).sort()).toEqual(graph.nodes.map((n) => n.id).sort());
    expect(countMetrics(all)).toBe(graph.nodes.length);
    const underStars = new Set(flatten(tree.roots).filter((r) => r.kind === "metric").map((r) => r.id));
    const unattached = new Set(flatten(tree.unattached).filter((r) => r.kind === "metric" && !r.ref).map((r) => r.id));
    for (const n of graph.nodes) expect(underStars.has(n.id) || unattached.has(n.id)).toBe(true);
    for (const id of unattached) expect(underStars.has(id)).toBe(false);
  });

  it("puts every north star in the tree, nested ones inside their parent outcome", () => {
    const placed = new Set(flatten(tree.roots).map((r) => r.id));
    for (const n of graph.nodes.filter((n) => n.north_star)) expect(placed.has(n.id)).toBe(true);
    const path = tree.home.payment_success_rate.split("/");
    expect(path[0]).toBe("gmv");
    expect(path).toContain("cvr");
  });

  it("survives the cause cycle sessions -> ad_impressions -> ad_clicks -> sessions", () => {
    const rows = flatten(all);
    expect(rows.length).toBeLessThan(400);
    const refs = rows.filter((r) => r.ref);
    expect(refs.length).toBeGreaterThan(0);
    for (const r of refs) expect(r.children).toHaveLength(0);
    const cause = rows.find((r) => r.via === "cause");
    expect(cause?.id).toBe("ad_clicks");
  });

  it("shows breakdowns as dimension rows and logs as leaves", () => {
    const rows = flatten(all);
    const dims = rows.filter((r) => r.kind === "dim");
    const logs = rows.filter((r) => r.kind === "log");
    expect(dims).toHaveLength(graph.edges.filter((e) => e.kind === "breakdown").length);
    expect(logs).toHaveLength(graph.edges.filter((e) => e.kind === "evidence").reduce((n, e) => n + e.sources.length, 0));
    for (const r of [...dims, ...logs]) expect(r.children).toHaveLength(0);
    const keys = rows.map((r) => r.key);
    expect(new Set(keys).size).toBe(keys.length);
  });

  it("opens the path down to a focused metric", () => {
    const open = openPathTo(tree, ["payment_success_rate"]);
    expect(open.has("gmv")).toBe(true);
    const home = tree.home.payment_success_rate;
    expect(open.has(home)).toBe(false);
    expect([...open].every((k) => home.startsWith(k))).toBe(true);
  });

  it("does not loop on a graph made only of a cycle", () => {
    const cyclic: Graph = {
      version: 1,
      logs: [],
      nodes: ["a", "b"].map((id) => ({ ...graph.nodes[0], id, north_star: true })),
      edges: [
        { ...graph.edges[0], id: "ab", kind: "formula", target: "a", sources: ["b"] },
        { ...graph.edges[0], id: "ba", kind: "formula", target: "b", sources: ["a"] },
      ],
    };
    const t = buildTree(cyclic);
    expect(countMetrics([...t.roots, ...t.unattached])).toBe(2);
  });
});
