// The ground plane keeps the reading order of the 2D graph.
import { describe, expect, it } from "vitest";
import { BLOCK, COLUMN, EXTRA_COLUMN, GRID, layout } from "../../../src/fx/scene/layout";
import { loadGraph } from "./fixtures";

describe("layout", () => {
  const graph = loadGraph();
  const placed = layout(graph);
  const pos = (id: string) => placed.get(id)!.position;

  it("gives every metric and log of the recorded graph a place from the grid", () => {
    for (const id of [...graph.nodes.map((n) => n.id), ...graph.logs.map((l) => l.id)]) {
      expect(placed.has(id), id).toBe(true);
      expect(GRID[id], id).toBeDefined();
    }
    expect(placed.size).toBe(31);
  });

  it("puts inputs left of outcomes and the shop behind the ads business", () => {
    expect(pos("sessions")[0]).toBeLessThan(pos("cvr")[0]);
    expect(pos("cvr")[0]).toBeLessThan(pos("gmv")[0]);
    expect(pos("gmv")[0]).toBeLessThan(pos("roas")[0]);
    // z grows toward the camera: the shop (top rows of the 2D graph) is farther away than the ads
    expect(pos("sessions")[2]).toBeLessThan(pos("ad_spend")[2]);
    expect(pos("gmv")[2]).toBeLessThan(pos("cpa")[2]);
  });

  it("stands every block on the ground, logs lower and back, north stars forward", () => {
    for (const [id, p] of placed) {
      expect(p.position[1], id).toBeCloseTo((BLOCK[1] * p.scale[1]) / 2);
    }
    const log = placed.get("log_deploys")!;
    const metric = placed.get("carts")!;
    expect(log.position[1]).toBeLessThan(metric.position[1]);
    const star = placed.get("gmv")!;
    expect(star.scale[1]).toBeGreaterThan(metric.scale[1]);
    // a log sits slightly behind its grid row, a north star slightly in front of it
    expect(log.position[2]).toBeLessThan((log.row - 5) * 1.38);
    expect(star.position[2]).toBeGreaterThan((star.row - 5) * 1.38);
  });

  it("keeps blocks of neighbouring columns apart", () => {
    expect(COLUMN).toBeGreaterThan(BLOCK[0] * 1.06);
  });

  it("lines unknown metrics up in a column of their own", () => {
    const more = layout({
      nodes: [...graph.nodes, { id: "new_a", north_star: false }, { id: "new_b", north_star: false }],
      logs: graph.logs,
    });
    const a = more.get("new_a")!;
    const b = more.get("new_b")!;
    expect(a.column).toBe(EXTRA_COLUMN);
    expect(b.column).toBe(EXTRA_COLUMN);
    expect(a.row).toBe(0);
    expect(b.row).toBe(1);
    expect(a.position[0]).toBeGreaterThan(Math.max(...[...placed.values()].map((p) => p.position[0])));
  });
});
