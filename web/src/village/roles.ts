// The seven agent roles of Argus, one igloo each. Positions are on the ground plane (x to the right, z toward
// the camera), in scene units; the 2D fallback projects the same coordinates. The case travels
// Watcher -> Detective -> Skeptic -> Narrator -> (your approval) -> Operator; the Cartographer and the Market
// Analyst are consulted on the way.

export type RoleId = "watcher" | "cartographer" | "detective" | "market" | "skeptic" | "narrator" | "operator";

export interface Role {
  id: RoleId;
  name: string;
  /** what the role does, in one plain line */
  job: string;
  /** what the role says when nothing is going on */
  idle: string;
  /** glow and scarf color */
  color: string;
  /** igloo center on the ground plane */
  x: number;
  z: number;
  /** direction the door faces, radians around the vertical axis (0 = toward the camera) */
  facing: number;
  /** igloo radius */
  size: number;
}

export const ROLES: readonly Role[] = [
  {
    id: "watcher",
    name: "Watcher",
    job: "Scores every metric each simulated hour and raises the alarm when one leaves its band.",
    idle: "Watching every metric, hour by hour",
    color: "#7cc4ff",
    x: -9.2,
    z: -0.6,
    facing: 0.55,
    size: 1.75,
  },
  {
    id: "cartographer",
    name: "Cartographer",
    job: "Keeps the metric map honest: tests every formula edge and follows a metric down its formula.",
    idle: "Every formula edge holds",
    color: "#a495ff",
    x: -5.6,
    z: -5.4,
    facing: 0.35,
    size: 1.55,
  },
  {
    id: "detective",
    name: "Detective",
    job: "Searches for the cause: where the change sits, when it started and what changed at that moment.",
    idle: "No open case",
    color: "#5aa7ff",
    x: -3.4,
    z: 1.6,
    facing: 0.15,
    size: 1.7,
  },
  {
    id: "market",
    name: "Market Analyst",
    job: "Compares the shop with the market, so a shared downturn is not filed as our fault.",
    idle: "Market index at hand",
    color: "#3fbf8f",
    x: 1.2,
    z: -5.6,
    facing: -0.05,
    size: 1.5,
  },
  {
    id: "skeptic",
    name: "Skeptic",
    job: "Tries to prove the Detective wrong: holdouts and placebo weeks rule out the false trails.",
    idle: "Nothing to doubt yet",
    color: "#f2785d",
    x: 2.8,
    z: 1.4,
    facing: -0.15,
    size: 1.65,
  },
  {
    id: "narrator",
    name: "Narrator",
    job: "Writes the verdict and the morning report, with a receipt behind every number.",
    idle: "Morning report up to date",
    color: "#e8b04a",
    x: 7.2,
    z: -3.0,
    facing: -0.4,
    size: 1.6,
  },
  {
    id: "operator",
    name: "Operator",
    job: "Acts only after your approval, then checks against an untouched twin that the action worked.",
    idle: "Nothing waits for your approval",
    color: "#36c9b6",
    x: 9.8,
    z: 1.9,
    facing: -0.6,
    size: 1.7,
  },
];

export const ROLE: Readonly<Record<RoleId, Role>> = Object.fromEntries(ROLES.map((r) => [r.id, r])) as Record<RoleId, Role>;

export const ROLE_IDS: readonly RoleId[] = ROLES.map((r) => r.id);

/** Where a role's character stands: just outside its door. */
export function doorstep(role: Role, out = 1.0): [number, number] {
  const d = role.size + out;
  return [role.x + Math.sin(role.facing) * d, role.z + Math.cos(role.facing) * d];
}

/** The approval post between the Narrator and the Operator, where a case waits for you. */
export const APPROVAL_POST: [number, number] = [8.2, -0.2];

/** The order the case visits the igloos in, for the paths drawn on the snow. */
export const PATHS: readonly [RoleId, RoleId][] = [
  ["watcher", "detective"],
  ["watcher", "cartographer"],
  ["cartographer", "detective"],
  ["detective", "market"],
  ["detective", "skeptic"],
  ["market", "skeptic"],
  ["skeptic", "narrator"],
  ["narrator", "operator"],
  ["operator", "watcher"],
];
