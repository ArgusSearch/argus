// Builds a browsable tree from the metric graph (C3). Pure: the same graph always gives the same tree.
//
// - The top of the tree is the north-star metrics that no other north star contains.
// - A metric's children, in this order: the sources of its formula edges; for a ratio without a formula,
//   its numerator and denominator; the sources of cause edges; one row per breakdown edge (a dimension);
//   one leaf per evidence edge (a log).
// - The graph is not a tree: a metric can sit under several parents, and cause edges can close cycles
//   (sessions -> ad_impressions -> ad_clicks -> sessions). Each metric is expanded once, at its shallowest
//   place (breadth first); every other occurrence is a reference that points there and has no children.
// - Metrics that no north star reaches are listed under `unattached`, each with its own subtree.

import type { EdgeKind, EdgeStatus, Graph, GraphEdge } from "../lib/types";

export type Via = EdgeKind | "ratio";

export interface TreeRow {
  /** unique per occurrence: the path of ids from the root */
  key: string;
  kind: "metric" | "dim" | "log";
  /** metric id, dimension name or log id */
  id: string;
  depth: number;
  /** how this row hangs under its parent; null for a root */
  via: Via | null;
  edge: GraphEdge | null;
  /** a metric already expanded elsewhere in the tree */
  ref: boolean;
  children: TreeRow[];
}

export interface Tree {
  roots: TreeRow[];
  unattached: TreeRow[];
  /** metric id -> key of the row where it is expanded */
  home: Record<string, string>;
}

interface ChildLink {
  kind: TreeRow["kind"];
  id: string;
  via: Via;
  edge: GraphEdge | null;
}

function childLinks(graph: Graph): Map<string, ChildLink[]> {
  const byTarget = new Map<string, GraphEdge[]>();
  for (const e of graph.edges) byTarget.set(e.target, [...(byTarget.get(e.target) ?? []), e]);
  const out = new Map<string, ChildLink[]>();
  for (const n of graph.nodes) {
    const edges = byTarget.get(n.id) ?? [];
    const links: ChildLink[] = [];
    const seen = new Set<string>();
    const add = (link: ChildLink) => {
      const k = `${link.kind}:${link.id}`;
      if (link.kind === "metric" && seen.has(k)) return;
      seen.add(k);
      links.push(link);
    };
    const formulas = edges.filter((e) => e.kind === "formula");
    for (const e of formulas) for (const s of e.sources) add({ kind: "metric", id: s, via: "formula", edge: e });
    if (n.kind === "ratio" && !formulas.length) {
      for (const part of [n.numerator, n.denominator]) if (part) add({ kind: "metric", id: part, via: "ratio", edge: null });
    }
    for (const e of edges.filter((e) => e.kind === "cause")) for (const s of e.sources) add({ kind: "metric", id: s, via: "cause", edge: e });
    for (const e of edges.filter((e) => e.kind === "breakdown")) add({ kind: "dim", id: e.dim ?? e.id, via: "breakdown", edge: e });
    for (const e of edges.filter((e) => e.kind === "evidence")) for (const s of e.sources) add({ kind: "log", id: s, via: "evidence", edge: e });
    out.set(n.id, links);
  }
  return out;
}

export function buildTree(graph: Graph): Tree {
  const metricIds = new Set(graph.nodes.map((n) => n.id));
  const links = childLinks(graph);
  const home: Record<string, string> = {};

  const children = (id: string) => (links.get(id) ?? []).filter((l) => l.kind !== "metric" || metricIds.has(l.id));

  /** Breadth-first expansion from the given roots; every metric is expanded at its first (shallowest) place. */
  const grow = (rootIds: string[]): TreeRow[] => {
    const roots: TreeRow[] = [];
    const queue: TreeRow[] = [];
    for (const id of rootIds) {
      if (home[id]) continue;
      const row: TreeRow = { key: id, kind: "metric", id, depth: 0, via: null, edge: null, ref: false, children: [] };
      home[id] = row.key;
      roots.push(row);
      queue.push(row);
    }
    while (queue.length) {
      const parent = queue.shift() as TreeRow;
      for (const link of children(parent.id)) {
        const key = `${parent.key}/${link.kind === "metric" ? link.id : `${link.kind}:${link.edge?.id ?? link.id}`}`;
        const isMetric = link.kind === "metric";
        const ref = isMetric && home[link.id] !== undefined;
        const row: TreeRow = { key, kind: link.kind, id: link.id, depth: parent.depth + 1, via: link.via, edge: link.edge, ref, children: [] };
        parent.children.push(row);
        if (isMetric && !ref) {
          home[link.id] = key;
          queue.push(row);
        }
      }
    }
    return roots;
  };

  // north stars that another north star already contains are shown inside it, not again at the top
  const northStars = graph.nodes.filter((n) => n.north_star).map((n) => n.id);
  const reach = (from: string): Set<string> => {
    const seen = new Set<string>();
    const stack = [from];
    while (stack.length) {
      const id = stack.pop() as string;
      for (const l of children(id)) {
        if (l.kind === "metric" && !seen.has(l.id)) {
          seen.add(l.id);
          stack.push(l.id);
        }
      }
    }
    return seen;
  };
  const reached = new Map(northStars.map((id) => [id, reach(id)]));
  const contained = (id: string) => northStars.some((other) => other !== id && reached.get(other)?.has(id) && !reached.get(id)?.has(other));
  const tops = northStars.filter((id) => !contained(id));
  // a set of north stars that all contain each other (a cycle) still needs one of them at the top
  for (const id of northStars) if (!tops.some((t) => t === id || reached.get(t)?.has(id))) tops.push(id);
  const roots = grow(tops);

  // what no north star reaches: start from metrics nothing points to, then whatever a cycle left over
  const parents = new Set<string>();
  for (const [, ls] of links) for (const l of ls) if (l.kind === "metric") parents.add(l.id);
  const rest = () => graph.nodes.map((n) => n.id).filter((id) => !home[id]);
  const unattached = grow(rest().filter((id) => !parents.has(id)));
  while (rest().length) unattached.push(...grow([rest()[0]]));

  return { roots, unattached, home };
}

/** Every row of the tree, depth first, in display order. */
export function flatten(rows: TreeRow[]): TreeRow[] {
  const out: TreeRow[] = [];
  const walk = (r: TreeRow) => {
    out.push(r);
    r.children.forEach(walk);
  };
  rows.forEach(walk);
  return out;
}

/** Keys of the rows that must be open so that the given metrics' home rows are visible. */
export function openPathTo(tree: Tree, ids: string[]): Set<string> {
  const open = new Set<string>();
  for (const id of ids) {
    const key = tree.home[id];
    if (!key) continue;
    const parts = key.split("/");
    for (let i = 1; i < parts.length; i++) open.add(parts.slice(0, i).join("/"));
  }
  return open;
}

export function countMetrics(rows: TreeRow[]): number {
  return flatten(rows).filter((r) => r.kind === "metric" && !r.ref).length;
}

export const VIA_LABEL: Record<Via, string> = {
  formula: "formula",
  ratio: "ratio of",
  cause: "possible cause",
  breakdown: "breakdown",
  evidence: "evidence",
};

export function statusOrNull(edge: GraphEdge | null, current: Record<string, { status: EdgeStatus }>): EdgeStatus | null {
  return edge ? (current[edge.id]?.status ?? edge.status) : null;
}
