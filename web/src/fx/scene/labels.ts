// Crisp DOM labels projected from 3D: each block's short name and |z| (at most 31), the tag the 2D graph shows,
// the numbered "+" markers of the trace (A7) and square brackets around the blocks being checked (A6).
// Text changes only when the model changes; positions are transforms written once per frame, and only when
// they moved.

import { Vector3, type PerspectiveCamera } from "three";
import { BLOCK } from "./layout";
import type { SceneNode } from "./model";
import type { TraceMarker } from "./trace";

const BRACKETS = 4;

interface Item {
  el: HTMLDivElement;
  tag: HTMLSpanElement;
  name: HTMLSpanElement;
  value: HTMLSpanElement;
  x: number;
  y: number;
  shown: boolean;
  text: string;
  cls: string;
}

interface Mark {
  el: HTMLDivElement;
  steps: HTMLSpanElement;
  x: number;
  y: number;
  shown: boolean;
}

interface Bracket {
  corners: HTMLSpanElement[];
  shown: boolean;
}

/** "1 2 3 4 7 9 10" becomes "1–4 · 7 · 9–10". */
export function stepRanges(steps: number[]): string {
  const parts: string[] = [];
  for (let i = 0; i < steps.length; ) {
    let j = i;
    while (j + 1 < steps.length && steps[j + 1] === steps[j] + 1) j += 1;
    parts.push(j > i ? `${steps[i]}–${steps[j]}` : `${steps[i]}`);
    i = j + 1;
  }
  return parts.join(" · ");
}

export class Labels {
  readonly root: HTMLDivElement;
  private readonly items = new Map<string, Item>();
  private marks = new Map<string, Mark>();
  private readonly brackets: Bracket[] = [];
  private readonly v = new Vector3();
  private readonly w = new Vector3();
  private size = 0;
  private far = false;
  private hovered: string | null = null;

  constructor(parent: HTMLElement) {
    this.root = document.createElement("div");
    this.root.className = "fxs-labels";
    parent.appendChild(this.root);
    for (let b = 0; b < BRACKETS; b++) {
      const corners: HTMLSpanElement[] = [];
      for (const c of ["tl", "tr", "bl", "br"]) {
        const s = document.createElement("span");
        s.className = `fxs-corner ${c}`;
        this.root.appendChild(s);
        corners.push(s);
      }
      this.brackets.push({ corners, shown: false });
    }
  }

  /** The block under the pointer shows its full label (the quiet metrics are collapsed otherwise). */
  setHover(id: string | null): void {
    if (id === this.hovered) return;
    if (this.hovered) this.items.get(this.hovered)?.el.classList.remove("hover");
    this.hovered = id;
    if (id) this.items.get(id)?.el.classList.add("hover");
  }

  /** Creates, updates and removes labels for the model's nodes; `path` is the affected path, if any. */
  setNodes(nodes: SceneNode[], path: ReadonlySet<string> = new Set()): void {
    const seen = new Set<string>();
    for (const n of nodes) {
      seen.add(n.id);
      let item = this.items.get(n.id);
      if (!item) {
        const el = document.createElement("div");
        el.className = "fxs-node";
        const tag = document.createElement("span");
        tag.className = "fxs-tag";
        const name = document.createElement("span");
        name.className = "fxs-name";
        const value = document.createElement("span");
        value.className = "fxs-z";
        el.append(tag, name, value);
        this.root.appendChild(el);
        item = { el, tag, name, value, x: Number.NaN, y: Number.NaN, shown: false, text: "", cls: "" };
        this.items.set(n.id, item);
      }
      const z = n.kind === "metric" ? (n.z === null ? "–" : n.z.toFixed(1)) : n.id;
      const text = `${n.northStar ? "★ " : ""}${n.label}|${z}|${n.tag ?? ""}`;
      if (text !== item.text) {
        item.text = text;
        item.name.textContent = `${n.northStar ? "★ " : ""}${n.label}`;
        item.value.textContent = n.kind === "metric" ? `z ${z}` : n.id;
        item.tag.textContent = n.tag ?? "";
      }
      const cls = `fxs-node ${n.kind} ${n.tone}${n.northStar ? " star" : ""}${n.focus ? " focus" : ""}${n.tag ? " tagged" : ""}${
        n.kind === "metric" && !n.scored && !n.focus ? " unscored" : ""
      }${path.has(n.id) ? " path" : path.size && !n.focus ? " recede" : ""}${n.id === this.hovered ? " hover" : ""}${item.shown ? " shown" : ""}`;
      if (cls !== item.cls) {
        item.cls = cls;
        item.el.className = cls;
      }
    }
    for (const [id, item] of this.items) {
      if (seen.has(id)) continue;
      item.el.remove();
      this.items.delete(id);
    }
  }

  setMarkers(markers: TraceMarker[]): void {
    const next = new Map<string, Mark>();
    for (const m of markers) {
      let mark = this.marks.get(m.id);
      if (!mark) {
        const el = document.createElement("div");
        el.className = "fxs-mark";
        const plus = document.createElement("span");
        plus.className = "fxs-plus";
        plus.textContent = "+";
        const steps = document.createElement("span");
        steps.className = "fxs-steps";
        el.append(plus, steps);
        this.root.appendChild(el);
        mark = { el, steps, x: Number.NaN, y: Number.NaN, shown: false };
      }
      mark.steps.textContent = stepRanges(m.steps);
      next.set(m.id, mark);
    }
    for (const [id, mark] of this.marks) if (!next.has(id)) mark.el.remove();
    this.marks = next;
  }

  /** Projects a world point to CSS pixels of the mount element. */
  private project(camera: PerspectiveCamera, x: number, y: number, z: number, canvasW: number, canvasH: number, ox: number, oy: number): boolean {
    this.v.set(x, y, z).project(camera);
    if (this.v.z > 1) return false;
    this.v.x = ((this.v.x + 1) / 2) * canvasW - ox;
    this.v.y = ((1 - this.v.y) / 2) * canvasH - oy;
    return true;
  }

  /**
   * Positions everything. `anchor(i)` gives the world point on top of block `i` of `nodes`; `visible(i)` says
   * whether its block has materialized. `ox, oy` is the mount's offset inside the canvas, `w, h` its size.
   */
  update(
    camera: PerspectiveCamera,
    nodes: SceneNode[],
    anchor: (i: number, out: Vector3) => Vector3,
    visible: (i: number) => boolean,
    focusBoxes: { center: Vector3; half: Vector3; hover: boolean }[],
    markers: TraceMarker[],
    drawn: number,
    traceOn: boolean,
    canvasW: number,
    canvasH: number,
    ox: number,
    oy: number,
    w: number,
    h: number,
    reference: Vector3,
  ): void {
    // label size follows the on-screen size of a block at the framing center
    camera.updateMatrixWorld();
    this.w.setFromMatrixColumn(camera.matrixWorld, 0).multiplyScalar(BLOCK[0] / 2);
    let blockPx = 0;
    if (this.project(camera, reference.x - this.w.x, reference.y - this.w.y, reference.z - this.w.z, canvasW, canvasH, 0, 0)) {
      const ax = this.v.x;
      const ay = this.v.y;
      if (this.project(camera, reference.x + this.w.x, reference.y + this.w.y, reference.z + this.w.z, canvasW, canvasH, 0, 0)) {
        blockPx = Math.hypot(this.v.x - ax, this.v.y - ay);
      }
    }
    const size = Math.round(Math.min(15, Math.max(10.5, blockPx * 0.088)) * 4) / 4;
    if (size !== this.size) {
      this.size = size;
      this.root.style.setProperty("--fxs-size", `${size}px`);
    }
    const far = blockPx < 70;
    if (far !== this.far) {
      this.far = far;
      this.root.classList.toggle("far", far);
    }

    for (let i = 0; i < nodes.length; i++) {
      const item = this.items.get(nodes[i].id);
      if (!item) continue;
      const a = anchor(i, this.w);
      let show = visible(i) && this.project(camera, a.x, a.y, a.z, canvasW, canvasH, ox, oy);
      show = show && this.v.x > -40 && this.v.x < w + 40 && this.v.y > -20 && this.v.y < h + 20;
      if (show && !(Math.abs(this.v.x - item.x) <= 0.2 && Math.abs(this.v.y - item.y) <= 0.2)) {
        item.x = this.v.x;
        item.y = this.v.y;
        item.el.style.transform = `translate3d(${item.x.toFixed(1)}px, ${item.y.toFixed(1)}px, 0)`;
      }
      if (show !== item.shown) {
        item.shown = show;
        item.el.classList.toggle("shown", show);
        item.cls = item.el.className;
      }
    }

    for (const m of markers) {
      const mark = this.marks.get(m.id);
      if (!mark) continue;
      const show = traceOn && drawn >= m.hop - 0.02 && this.project(camera, m.point[0], m.point[1], m.point[2], canvasW, canvasH, ox, oy);
      if (show && !(Math.abs(this.v.x - mark.x) <= 0.2 && Math.abs(this.v.y - mark.y) <= 0.2)) {
        mark.x = this.v.x;
        mark.y = this.v.y;
        mark.el.style.transform = `translate3d(${mark.x.toFixed(1)}px, ${mark.y.toFixed(1)}px, 0)`;
      }
      if (show !== mark.shown) {
        mark.shown = show;
        mark.el.classList.toggle("shown", show);
      }
    }

    for (let b = 0; b < BRACKETS; b++) {
      const bracket = this.brackets[b];
      const box = focusBoxes[b];
      let show = false;
      if (box) {
        let minX = Infinity;
        let minY = Infinity;
        let maxX = -Infinity;
        let maxY = -Infinity;
        show = true;
        for (let k = 0; k < 8 && show; k++) {
          const sx = k & 1 ? 1 : -1;
          const sy = k & 2 ? 1 : -1;
          const sz = k & 4 ? 1 : -1;
          show = this.project(
            camera,
            box.center.x + sx * box.half.x,
            box.center.y + sy * box.half.y,
            box.center.z + sz * box.half.z,
            canvasW,
            canvasH,
            ox,
            oy,
          );
          minX = Math.min(minX, this.v.x);
          maxX = Math.max(maxX, this.v.x);
          minY = Math.min(minY, this.v.y);
          maxY = Math.max(maxY, this.v.y);
        }
        if (show) {
          const pad = 7;
          const [tl, tr, bl, br] = bracket.corners;
          tl.style.transform = `translate3d(${(minX - pad).toFixed(1)}px, ${(minY - pad).toFixed(1)}px, 0)`;
          tr.style.transform = `translate3d(${(maxX + pad).toFixed(1)}px, ${(minY - pad).toFixed(1)}px, 0)`;
          bl.style.transform = `translate3d(${(minX - pad).toFixed(1)}px, ${(maxY + pad).toFixed(1)}px, 0)`;
          br.style.transform = `translate3d(${(maxX + pad).toFixed(1)}px, ${(maxY + pad).toFixed(1)}px, 0)`;
          for (const c of bracket.corners) c.classList.toggle("hover", box.hover);
        }
      }
      if (show !== bracket.shown) {
        bracket.shown = show;
        for (const c of bracket.corners) c.classList.toggle("shown", show);
      }
    }
  }

  dispose(): void {
    this.root.remove();
    this.items.clear();
    this.marks.clear();
  }
}
