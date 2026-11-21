// Where every metric and log stands on the ground plane of the 3D graph. Pure: no Three.js, no DOM.
//
// The reading order is the one of the 2D graph (GraphView's grid): inputs on the left, outcomes on the right,
// the shop above, the ads business below. On the ground that becomes x to the right and z toward the camera,
// so "above" is farther away. Logs sit one step back and lower, north-star metrics one step forward and higher.
// Metrics the graph learns later get a column of their own, right of everything else.

export type Vec3 = [number, number, number];

/** [column, row] of the known metrics and logs. */
export const GRID: Readonly<Record<string, readonly [number, number]>> = {
  log_calendar: [0, 0],
  log_deploys: [0, 3.2],
  log_provider_status: [0, 6],
  sessions: [1, 0],
  product_views: [1, 1],
  carts: [1, 2],
  checkouts: [1, 3],
  payment_attempts: [1, 4],
  payment_successes: [1, 5],
  view_rate: [2, 1],
  cart_rate: [2, 2],
  checkout_rate: [2, 3],
  attempt_rate: [2, 4],
  payment_success_rate: [2, 5],
  cvr: [3, 3],
  orders: [4, 2],
  aov: [4, 4],
  gmv: [5, 3],
  impressions_per_session: [2, 7],
  ad_impressions: [3, 7],
  ctr: [3, 8],
  ad_clicks: [4, 7.5],
  cpc: [4, 8.5],
  ad_spend: [5, 8],
  attributed_gmv: [5, 6.6],
  log_ad_budgets: [4, 9.8],
  planned_spend: [5, 9.3],
  ad_conversions: [5, 10.3],
  roas: [6, 6.9],
  pacing_ratio: [6, 8.6],
  cpa: [6, 9.8],
};

/** World units between two columns and two rows. */
export const COLUMN = 3.3;
export const ROW = 1.38;

/** Size of a metric block (x, y, z); logs and north stars scale it (see BLOCK_SCALE). */
export const BLOCK: Vec3 = [2.6, 0.46, 0.92];
export const BLOCK_SCALE = {
  metric: [0.86, 0.78, 0.86] as Vec3,
  northStar: [1.2, 1.55, 1.14] as Vec3,
  log: [0.8, 0.4, 0.8] as Vec3,
};

/** Logs one step back and lower, north stars one step forward. */
const LOG_BACK = -0.34;
const STAR_FORWARD = 0.16;

const CENTER_COLUMN = 3;
const CENTER_ROW = 5;

export interface Placement {
  column: number;
  row: number;
  /** Center of the block; y is half its height, so it stands on the ground. */
  position: Vec3;
  scale: Vec3;
}

export interface LayoutInput {
  nodes: { id: string; north_star: boolean }[];
  logs: { id: string }[];
}

/** The column after every known one: where metrics outside the grid line up. */
export const EXTRA_COLUMN = Math.max(...Object.values(GRID).map(([c]) => c)) + 1;

/**
 * `stretch` widens the column spacing (1 = the reading order's natural width); the scene uses it to fill a
 * wide panel instead of leaving its sides empty.
 */
export function layout(graph: LayoutInput, stretch = 1): Map<string, Placement> {
  const out = new Map<string, Placement>();
  let extraRow = 0;
  const place = (id: string, kind: "metric" | "northStar" | "log") => {
    const cell = GRID[id] ?? [EXTRA_COLUMN, extraRow++];
    const scale = BLOCK_SCALE[kind];
    const shift = kind === "log" ? LOG_BACK : kind === "northStar" ? STAR_FORWARD : 0;
    out.set(id, {
      column: cell[0],
      row: cell[1],
      position: [(cell[0] - CENTER_COLUMN) * COLUMN * stretch, (BLOCK[1] * scale[1]) / 2, (cell[1] - CENTER_ROW) * ROW + shift],
      scale,
    });
  };
  for (const n of graph.nodes) place(n.id, n.north_star ? "northStar" : "metric");
  for (const l of graph.logs) if (!out.has(l.id)) place(l.id, "log");
  return out;
}
