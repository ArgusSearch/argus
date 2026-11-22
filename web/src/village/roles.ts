// The seven agent roles of Argus, one igloo each. Positions are on the ground plane (x to the right, z toward
// the camera), in scene units; every igloo is cut open toward the camera (facing 0); the 2D fallback projects
// the same coordinates. Back row: Watcher, Detective, Skeptic; middle: Narrator, Market Analyst; front:
// Operator, Cartographer. The case travels
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
    idle: "Waiting for a metric tick",
    color: "#7cc4ff",
    x: -7.6,
    z: -7.2,
    facing: 0,
    size: 2.25,
  },
  {
    id: "cartographer",
    name: "Cartographer",
    job: "Keeps the metric map honest: tests every formula edge and follows a metric down its formula.",
    idle: "Waiting for a formula or placement check",
    color: "#a495ff",
    x: 4.4,
    z: 7.0,
    facing: 0,
    size: 2.25,
  },
  {
    id: "detective",
    name: "Detective",
    job: "Searches for the cause: where the change sits, when it started and what changed at that moment.",
    idle: "No open case",
    color: "#5aa7ff",
    x: 0.0,
    z: -7.6,
    facing: 0,
    size: 2.25,
  },
  {
    id: "market",
    name: "Market Analyst",
    job: "Compares the shop with the market, so a shared downturn is not filed as our fault.",
    idle: "Waiting for a market comparison",
    color: "#3fbf8f",
    x: 7.8,
    z: 0.3,
    facing: 0,
    size: 2.15,
  },
  {
    id: "skeptic",
    name: "Skeptic",
    job: "Tries to prove the Detective wrong: holdouts and placebo weeks rule out the false trails.",
    idle: "Nothing to doubt yet",
    color: "#f2785d",
    x: 7.6,
    z: -7.2,
    facing: 0,
    size: 2.25,
  },
  {
    id: "narrator",
    name: "Narrator",
    job: "Writes the verdict and the morning report, with a receipt behind every number.",
    idle: "Waiting for findings to report",
    color: "#e8b04a",
    x: -7.8,
    z: 0.3,
    facing: 0,
    size: 2.15,
  },
  {
    id: "operator",
    name: "Operator",
    job: "Acts only after your approval, then checks against an untouched twin that the action worked.",
    idle: "Nothing waits for your approval",
    color: "#36c9b6",
    x: -4.4,
    z: 7.0,
    facing: 0,
    size: 2.25,
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
export const APPROVAL_POST: [number, number] = [-8.9, 5.4];

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
