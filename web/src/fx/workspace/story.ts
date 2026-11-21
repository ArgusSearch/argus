// The visualization's incident story: the chain from the number a person cares about (revenue) down the formulas
// to the metric that broke, then the logged change that caused it and the suspects that were ruled out. Played
// step by step, each step becomes the scene's focus, so the map lights the path the investigation took.
// The chain and the story are pure; the player is a tiny store the visualization and the app share.

import { useSyncExternalStore } from "react";
import { eur } from "../../lib/format";
import type { Focus } from "../../lib/store";
import type { Graph, Incident } from "../../lib/types";
import { metricName, wherePhrase } from "./plain";

/** The formula chain from the top of the graph down to `root`: [gmv, orders, cvr, payment_success_rate]. */
export function formulaChain(graph: Graph, root: string): { nodes: string[]; edges: string[] } {
  const formulas = graph.edges.filter((e) => e.kind === "formula" && Array.isArray(e.sources));
  const star = new Set(graph.nodes.filter((n) => n.north_star).map((n) => n.id));
  // breadth-first upwards: which formula uses this node as a factor; north-star targets first
  const up = new Map<string, { node: string; edge: string } | null>([[root, null]]);
  let frontier = [root];
  let top = root;
  while (frontier.length) {
    const next: string[] = [];
    for (const id of frontier) {
      const users = formulas
        .filter((e) => (e.sources ?? []).includes(id) && !up.has(e.target))
        .sort((a, b) => Number(star.has(b.target)) - Number(star.has(a.target)));
      for (const e of users) {
        up.set(e.target, { node: id, edge: e.id });
        next.push(e.target);
      }
    }
    if (next.length) top = next.find((t) => star.has(t)) ?? next[0];
    frontier = next;
  }
  const nodes: string[] = [];
  const edges: string[] = [];
  for (let at: string | undefined = top; at !== undefined; ) {
    nodes.push(at);
    const step = up.get(at);
    if (!step) break;
    edges.push(step.edge);
    at = step.node;
  }
  return { nodes, edges };
}

export interface StoryStep {
  key: string;
  /** what the step says, in plain words */
  text: string;
  /** a number to show with it (the loss, the change) */
  value?: string;
  kind: "effect" | "root" | "cause" | "ruled";
  focus: Focus;
}

export interface Story {
  incident: string;
  steps: StoryStep[];
}

/** The story of an incident on the map, top to bottom, then the cause and what was ruled out. */
export function storyOf(graph: Graph, incident: Incident): Story {
  const f = incident.findings;
  const root = f.root?.node ?? incident.root_node;
  const chain = formulaChain(graph, root);
  const lost = eur(Math.abs(incident.severity_eur));
  const down = incident.direction === "down";
  const steps: StoryStep[] = chain.nodes.map((node, i) => {
    const isRoot = node === root;
    const edge = chain.edges[i - 1];
    const text =
      i === 0
        ? `${metricName(graph, node)} ${down ? "fell" : "rose"}`
        : isRoot
          ? `because ${metricName(graph, node).toLowerCase()} ${down ? "fell" : "rose"} for ${wherePhrase(f.root?.segment ?? incident.segment)}`
          : `because ${metricName(graph, node).toLowerCase()} ${down ? "fell" : "rose"}`;
    const value = i === 0 ? `${down ? "-" : "+"}${lost}` : isRoot && f.root ? `${f.root.change_pct.value > 0 ? "+" : ""}${f.root.change_pct.value.toFixed(1)}%` : undefined;
    return {
      key: node,
      text,
      value,
      kind: isRoot ? "root" : "effect",
      focus: { nodes: [node], edges: edge ? [edge] : [], logs: [], tags: { [node]: value ?? (down ? "fell" : "rose") } },
    };
  });
  const evidence = f.root?.evidence;
  if (evidence) {
    steps.push({
      key: `cause:${evidence.ref}`,
      text: `Cause: ${evidence.description}`,
      kind: "cause",
      focus: { nodes: [root], edges: [], logs: [evidence.log], tags: { [evidence.log]: "supported cause" } },
    });
  }
  for (const r of f.ruled_out) {
    if (!r.evidence) continue;
    steps.push({
      key: `ruled:${r.evidence.ref}`,
      text: r.evidence.description,
      kind: "ruled",
      focus: { nodes: [], edges: [], logs: [r.evidence.log], tags: { [r.evidence.log]: "✕ ruled out" } },
    });
  }
  return { incident: incident.id, steps };
}

/** Everything lit at once: the whole chain, the cause, and the ruled-out suspects (the story's last frame). */
export function storyFocus(story: Story, upTo: number): Focus {
  const shown = story.steps.slice(0, upTo + 1);
  const tags: Record<string, string> = {};
  for (const s of shown) Object.assign(tags, s.focus.tags ?? {});
  return {
    nodes: [...new Set(shown.flatMap((s) => s.focus.nodes))],
    edges: [...new Set(shown.flatMap((s) => s.focus.edges))],
    logs: [...new Set(shown.flatMap((s) => s.focus.logs))],
    tags,
  };
}

/* ------------------------------------------------------------------ player */

type Listener = () => void;
const listeners = new Set<Listener>();
let focus: Focus | null = null;

/** The focus the story puts on the scene right now, or null when no story plays. */
export function setStoryFocus(next: Focus | null) {
  if (next === focus) return;
  focus = next;
  for (const l of [...listeners]) l();
}

export function useStoryFocus(): Focus | null {
  return useSyncExternalStore(
    (l) => {
      listeners.add(l);
      return () => listeners.delete(l);
    },
    () => focus,
    () => null,
  );
}
