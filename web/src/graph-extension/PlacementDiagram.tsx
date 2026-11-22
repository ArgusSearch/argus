// Where the new metric sits, drawn as it lands: its parents (the formulas that decompose it) on the left, the
// metric in the middle, the formulas it feeds on the right, its breakdowns below. The node pops in and each wire
// draws itself, so the placement reads as a movement. A rejected metric shows the join that fanned out instead.

import { labelOf, type PlacementView } from "./model";
import type { PlacementResult } from "./types";

const W = 480;
const CHIP_W = 134;
const CHIP_H = 22;
const NODE_W = 168;
const NODE_H = 40;
const GROUP_GAP = 20;
const PAD = 8;

const clip = (s: string, n = 21) => (s.length > n ? `${s.slice(0, n - 1)}…` : s);

function wireClass(status: string): string {
  if (status === "ALTERNATIVE") return "gx-wire alt";
  if (status === "PROBATION") return "gx-wire watch";
  if (status === "REJECTED") return "gx-wire bad";
  return "gx-wire good";
}

function Chip({ x, y, id, tone, delay, raw }: { x: number; y: number; id: string; tone?: string; delay: number; raw?: boolean }) {
  return (
    <g className={`gx-chip${tone ? ` ${tone}` : ""}${raw ? " raw" : ""}`} style={{ animationDelay: `${delay}s` }}>
      <rect x={x} y={y} width={CHIP_W} height={CHIP_H} rx={6} />
      <text x={x + 8} y={y + CHIP_H / 2 + 4}>
        {clip(raw ? id : labelOf(id))}
      </text>
    </g>
  );
}

function Wire({ d, status, delay }: { d: string; status: string; delay: number }) {
  return <path className={wireClass(status)} d={d} pathLength={1} style={{ animationDelay: `${delay}s` }} />;
}

const curve = (x1: number, y1: number, x2: number, y2: number) => {
  const mx = (x1 + x2) / 2;
  return `M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`;
};

export function PlacementDiagram({ view, placement }: { view: PlacementView; placement: PlacementResult }) {
  const rejected = view.verdict === "REJECTED";
  const tables = [...new Set(placement.metric.sql.match(/fact_[a-z_]+/g) ?? [])];
  const groups = rejected
    ? [{ id: "join", sources: tables, status: "REJECTED", reads: "", evidence: "" }]
    : view.routes.length
      ? view.routes
      : [];
  const groupH = (n: number) => n * CHIP_H + (n - 1) * 4;
  const leftH = groups.reduce((h, g) => h + groupH(g.sources.length), 0) + Math.max(0, groups.length - 1) * GROUP_GAP;
  const rightH = view.feeds.length * (CHIP_H + 18) - (view.feeds.length ? 18 : 0);
  const bodyH = Math.max(leftH, rightH, NODE_H);
  const dimsH = view.dims.length ? 22 : 0;
  const H = bodyH + dimsH + PAD * 2;
  const nodeX = (W - NODE_W) / 2;
  const nodeY = PAD + bodyH / 2 - NODE_H / 2;
  const midY = nodeY + NODE_H / 2;
  const nodeTone = rejected ? "bad" : view.verdict === "AMBIGUOUS" ? "watch" : "good";

  let y = PAD + (bodyH - leftH) / 2;
  const left = groups.map((g, gi) => {
    const top = y;
    y += groupH(g.sources.length) + GROUP_GAP;
    const cy = top + groupH(g.sources.length) / 2;
    const tone = g.status === "ALTERNATIVE" ? "alt" : undefined;
    return (
      <g key={g.id}>
        {g.sources.map((s, i) => (
          <Chip key={s} x={PAD} y={top + i * (CHIP_H + 4)} id={s} tone={tone} raw={rejected} delay={0.15 + gi * 0.25 + i * 0.06} />
        ))}
        {g.sources.length > 1 && !rejected && (
          <text className="gx-op" x={PAD + CHIP_W + 10} y={cy + 4}>
            ×
          </text>
        )}
        <Wire d={curve(PAD + CHIP_W + 22, cy, nodeX, midY)} status={g.status} delay={0.45 + gi * 0.25} />
        {g.status === "ALTERNATIVE" && (
          <text className="gx-wire-label" x={PAD + 2} y={top - 5}>
            alternative parent
          </text>
        )}
        {g.status === "PROBATION" && (
          <text className="gx-wire-label watch" x={PAD + CHIP_W + 26} y={cy - 7}>
            probation · ½ weight
          </text>
        )}
      </g>
    );
  });

  let fy = PAD + (bodyH - rightH) / 2;
  const right = view.feeds.map((f, i) => {
    const top = fy;
    fy += CHIP_H + 18;
    const x = W - PAD - CHIP_W;
    return (
      <g key={f.id}>
        <Wire d={curve(nodeX + NODE_W, midY, x, top + CHIP_H / 2)} status={f.status} delay={0.75 + i * 0.15} />
        <Chip x={x} y={top} id={f.target} delay={0.9 + i * 0.15} />
        <text className="gx-feed-label" x={x + 2} y={top + CHIP_H + 12}>
          {clip(`= ${f.other.map(labelOf).join(" × ")} × this`, 26)}
        </text>
      </g>
    );
  });

  return (
    <svg className="gx-diagram" viewBox={`0 0 ${W} ${H}`} role="img" aria-label={`${view.label}: ${view.headline}`}>
      {left}
      {right}
      <g className={`gx-node ${nodeTone}`}>
        <rect x={nodeX} y={nodeY} width={NODE_W} height={NODE_H} rx={9} />
        <text className="gx-node-label" x={W / 2} y={nodeY + 17} textAnchor="middle">
          {clip(view.label, 25)}
        </text>
        <text className="gx-node-sub" x={W / 2} y={nodeY + 31} textAnchor="middle">
          {rejected && placement.repair ? `fan-out ×${placement.repair.factor.toFixed(2)}` : placement.node ? `${placement.node.kind} · ${placement.node.unit}` : view.verdict.toLowerCase()}
        </text>
        {rejected && <path className="gx-cross" d={`M${nodeX + NODE_W - 15},${nodeY - 4} l9,9 m0,-9 l-9,9`} />}
      </g>
      {view.dims.length > 0 && (
        <text className="gx-dims" x={W / 2} y={PAD + bodyH + 18} textAnchor="middle">
          {`breakdowns by ${view.dims.join(" · ")}`}
        </text>
      )}
    </svg>
  );
}
