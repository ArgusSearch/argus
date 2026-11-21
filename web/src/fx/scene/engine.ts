// The imperative side of the 3D graph. GraphScene hands it the props; it owns the renderer, the render loop and
// every effect. React never re-renders scene objects: inputs mark the model dirty, and the next animation frame
// rebuilds it once and diffs it against the previous one to start the events (crack, refreeze, freeze-in, pulses).

import { Color, Scene, Vector2, Vector3, WebGLRenderer } from "three";
import type { RunView } from "../../lib/store";
import type { Graph } from "../../lib/types";
import { Blocks } from "./blocks";
import { Edges, WIDTH, type BlockBox } from "./edges";
import { createEnv } from "./env";
import { Ground } from "./ground";
import { Labels } from "./labels";
import { BLOCK, layout, type Placement } from "./layout";
import { currentInvestigation, incidentPath, nodeTitle, ruledOut, sceneModel, type NodeTone, type SceneModel, type SceneNode } from "./model";
import { color, readPaletteHex, type PaletteHex } from "./palette";
import { Bursts, Snow } from "./particles";
import { Post } from "./post";
import { AdaptiveQuality, pixelRatio, TIERS, type QualityMode, type TierSpec } from "./quality";
import { CameraRig, columnStretch, type SafeRect } from "./rig";
import { Trace } from "./trace";

export const SCENE_READY = "fx:scene-ready";
export const INTRO = "fx:intro";
export const QUALITY = "fx:quality";
export const THEME = "fx:theme";

/** How long the scene waits for the layer's intro cue before it starts on its own. */
const INTRO_WAIT = 1.5;
const DEFAULT_INTRO = 3;
const FREEZE_IN = 1.8;
const VISIT = 4.5;
/** seconds a learned metric keeps its "new metric" tag */
const FRESH = 10;
const VERDICT_HOLD = 4;

export interface EngineOptions {
  mount: HTMLDivElement;
  onSelect: (id: string) => void;
  onFail: (error: Error) => void;
  quality: QualityMode;
  /** play no intro when the cue does not come (fxintro=0 on a page without the layer) */
  skipIntro: boolean;
  /** expose frame statistics on window.__fxScene (lab page, fxdebug=1) */
  debug: boolean;
  /**
   * A small preview (the dashboard's "affected path" card): the canvas stays inside the mount, the scene
   * neither waits for nor sends the layer's events, and the camera frames the affected path.
   */
  preview: boolean;
}

export interface SceneStats {
  fps: number;
  worstMs: number;
  cpuMs: number;
  calls: number;
  triangles: number;
  points: number;
  pixelRatio: number;
  width: number;
  height: number;
  tier: string;
  bloom: boolean;
  /** what the camera frames: overview, investigation, verdict, visit or path */
  camera: string;
}

interface Palette {
  hex: PaletteHex;
  fog: Color;
  ground: Color;
  hud: Color;
  rim: Color;
  lit: Color;
  shade: Color;
  shadow: Color;
  snow: Color;
  glow: Record<keyof PaletteHex["glow"], Color>;
  edge: Record<keyof PaletteHex["edge"], Color>;
}

function makePalette(hex: PaletteHex): Palette {
  const map = <T extends Record<string, string>>(o: T) =>
    Object.fromEntries(Object.entries(o).map(([k, v]) => [k, color(v)])) as Record<keyof T, Color>;
  return {
    hex,
    fog: color(hex.fog),
    ground: color(hex.ground),
    hud: color(hex.hud.color),
    rim: color(hex.rim),
    lit: color(hex.blockLit),
    shade: color(hex.blockShade),
    shadow: color(hex.shadow.color),
    snow: color(hex.snow.color),
    glow: map(hex.glow),
    edge: Object.fromEntries(Object.entries(hex.edge).map(([k, v]) => [k, color(v.color)])) as Record<keyof PaletteHex["edge"], Color>,
  };
}

/** Per-block animation state, kept by id across model rebuilds. */
interface Visual {
  core: Color;
  glow: number;
  crack: number;
  dim: number;
  highlight: number;
  flash: number;
  shake: number;
  path: number;
  seed: number;
  /** materialize: -1 waits for the intro, otherwise the time it started and how long it takes */
  start: number;
  duration: number;
  m: number;
}

interface LinkVisual {
  focus: number;
  path: number;
  reveal: number;
  pulse: number;
  pending: boolean;
}

const ALARMED: ReadonlySet<NodeTone> = new Set(["alarm", "root"]);

const ease = (t: number) => (t <= 0 ? 0 : t >= 1 ? 1 : t * t * (3 - 2 * t));
const easeOut = (t: number) => (t <= 0 ? 0 : t >= 1 ? 1 : 1 - Math.pow(1 - t, 3));
const approach = (x: number, target: number, rate: number, dt: number) => x + (target - x) * (1 - Math.exp(-rate * dt));

export class SceneEngine {
  private readonly opts: EngineOptions;
  private readonly renderer: WebGLRenderer;
  private readonly canvas: HTMLCanvasElement;
  private readonly stage: HTMLElement | null;
  private readonly scene = new Scene();
  private readonly env = createEnv();
  private readonly rig = new CameraRig();
  private readonly blocks: Blocks;
  private readonly edges: Edges;
  private readonly ground: Ground;
  private readonly snow: Snow;
  private readonly bursts: Bursts;
  private readonly trace: Trace;
  private readonly post: Post;
  private readonly labels: Labels;
  private readonly adaptive = new AdaptiveQuality();
  private palette: Palette;
  private reducedMotion: boolean;

  private graph: Graph | null = null;
  private view: RunView | null = null;
  private dirty = false;
  private model: SceneModel | null = null;
  private placed = new Map<string, Placement>();
  private nodes: SceneNode[] = [];
  private nodeIndex = new Map<string, number>();
  private visuals = new Map<string, Visual>();
  private linkVisuals: LinkVisual[] = [];
  private linkIds: string[] = [];
  private structure = "";
  private stretch = 1;
  private ruled = new Set<string>();
  /** the affected path of the open investigation; empty when there is none */
  private path = new Set<string>();
  private edgeChanges = 0;
  private fresh = new Map<string, number>();

  private time = 0;
  private last = 0;
  private raf = 0;
  private running = false;
  private disposed = false;
  private frames = 0;
  private ready = false;
  private readyAt = -1;
  private introStart = -1;
  private introDuration = 0;
  private pendingIntro: number | null = null;
  private verdictAt = -1;
  private visitUntil = -1;
  private visitIds: string[] = [];
  private framingKey = "";
  private cameraMode = "overview";

  private canvasW = 1;
  private canvasH = 1;
  private rect: SafeRect = { canvasWidth: 1, canvasHeight: 1, x: 0, y: 0, width: 1, height: 1 };
  /** where the canvas starts in the viewport */
  private canvasLeft = 0;
  private canvasTop = 0;
  private rectDirty = true;
  private sizeDirty = true;
  private mountVisible = true;
  private pageVisible = !document.hidden;

  private pointerWindow: { x: number; y: number } | null = null;
  private pointerClient: { x: number; y: number } | null = null;
  private pointerDirty = false;
  private hover = -1;

  private tier: TierSpec;
  private tierName = "";
  private pr = 1;
  private lostTimer = 0;
  private stats: SceneStats = { fps: 0, worstMs: 0, cpuMs: 0, calls: 0, triangles: 0, points: 0, pixelRatio: 1, width: 0, height: 0, tier: "", bloom: true, camera: "overview" };
  private statFrames = 0;
  private statTime = 0;
  private statWorst = 0;
  private measured = false;

  // scratch, so the frame loop allocates nothing
  private readonly tmpColor = new Color();
  private readonly tmpV = new Vector3();
  private readonly rayDir = new Vector3();
  private readonly ndc = new Vector2();
  private readonly ringCenter = new Vector2();
  private readonly focusBoxes: { center: Vector3; half: Vector3; hover: boolean }[] = [];
  private readonly boxPool = Array.from({ length: 4 }, () => ({ center: new Vector3(), half: new Vector3(), hover: false }));
  private readonly cleanups: (() => void)[] = [];

  constructor(opts: EngineOptions) {
    this.opts = opts;
    this.stage = opts.preview ? null : document.getElementById("fx-stage");
    this.reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.tier = TIERS[opts.quality === "auto" ? "high" : opts.quality];

    this.canvas = document.createElement("canvas");
    this.canvas.className = "fxs-canvas";
    this.canvas.setAttribute("aria-hidden", "true");
    this.renderer = new WebGLRenderer({
      canvas: this.canvas,
      antialias: false,
      alpha: false,
      depth: false,
      stencil: false,
      powerPreference: "high-performance",
    });
    this.renderer.autoClear = false;
    this.renderer.info.autoReset = false;
    (this.stage ?? opts.mount).prepend(this.canvas);

    this.blocks = new Blocks(this.env);
    this.edges = new Edges(this.env);
    this.ground = new Ground(this.env);
    this.snow = new Snow(this.env);
    this.bursts = new Bursts(this.env);
    this.trace = new Trace(this.env);
    this.post = new Post(this.tier.samples);
    this.labels = new Labels(opts.mount);
    this.labels.root.classList.toggle("preview", opts.preview);
    this.scene.add(this.ground.mesh, this.blocks.shadows, this.blocks.mesh, this.edges.ribbons, this.edges.flow, this.bursts.points, this.snow.points, this.trace.mesh);

    this.palette = makePalette(readPaletteHex());
    this.applyPalette();
    this.applyTier();
    this.listen();
    this.start();
  }

  // ------------------------------------------------------------------ inputs

  setInputs(graph: Graph, view: RunView): void {
    this.graph = graph;
    this.view = view;
    this.dirty = true;
    if (!this.running) this.start();
  }

  // ------------------------------------------------------------------ lifecycle

  private listen(): void {
    const on = <K extends string>(target: EventTarget, type: K, fn: (e: Event) => void, opts?: AddEventListenerOptions) => {
      target.addEventListener(type, fn, opts);
      this.cleanups.push(() => target.removeEventListener(type, fn, opts));
    };
    const mount = this.opts.mount;

    on(window, INTRO, (e) => {
      if (this.opts.preview) return;
      const ms = Number((e as CustomEvent<{ duration?: number }>).detail?.duration);
      this.requestIntro(Number.isFinite(ms) ? Math.max(0, ms) / 1000 : DEFAULT_INTRO);
    });
    on(window, THEME, () => this.reloadPalette());
    const themeObserver = new MutationObserver(() => this.reloadPalette());
    themeObserver.observe(document.documentElement, { attributes: true, attributeFilter: ["data-fx"] });
    this.cleanups.push(() => themeObserver.disconnect());

    const motion = matchMedia("(prefers-reduced-motion: reduce)");
    on(motion, "change", () => {
      this.reducedMotion = motion.matches;
      this.applyTier();
    });

    on(document, "visibilitychange", () => {
      this.pageVisible = !document.hidden;
      this.updateRunning();
    });
    const seen = new IntersectionObserver((entries) => {
      const entry = entries[entries.length - 1];
      this.mountVisible = entry.isIntersecting;
      this.canvas.classList.toggle("live", this.ready && this.mountVisible);
      this.rectDirty = true;
      this.updateRunning();
    });
    seen.observe(mount);
    this.cleanups.push(() => seen.disconnect());

    const resized = new ResizeObserver(() => {
      this.sizeDirty = true;
      this.rectDirty = true;
    });
    resized.observe(mount);
    if (this.stage) resized.observe(this.stage);
    this.cleanups.push(() => resized.disconnect());
    on(window, "resize", () => {
      this.sizeDirty = true;
      this.rectDirty = true;
    });
    on(window, "scroll", () => (this.rectDirty = true), { capture: true, passive: true });

    on(
      window,
      "pointermove",
      (e) => {
        const p = e as PointerEvent;
        this.pointerWindow = { x: (p.clientX / window.innerWidth) * 2 - 1, y: -((p.clientY / window.innerHeight) * 2 - 1) };
      },
      { passive: true },
    );
    on(document.documentElement, "pointerleave", () => (this.pointerWindow = null));
    on(mount, "pointermove", (e) => {
      const p = e as PointerEvent;
      this.pointerClient = { x: p.clientX, y: p.clientY };
      this.pointerDirty = true;
    });
    on(mount, "pointerleave", () => {
      this.pointerClient = null;
      this.pointerDirty = true;
    });
    on(mount, "click", (e) => {
      const p = e as MouseEvent;
      const hit = this.pick(p.clientX, p.clientY);
      if (hit >= 0) this.opts.onSelect(this.nodes[hit].id);
    });

    on(this.canvas, "webglcontextlost", (e) => {
      e.preventDefault();
      this.stop();
      window.clearTimeout(this.lostTimer);
      this.lostTimer = window.setTimeout(() => this.opts.onFail(new Error("the WebGL context was lost and not restored")), 2500);
    });
    on(this.canvas, "webglcontextrestored", () => {
      window.clearTimeout(this.lostTimer);
      this.edges.commit();
      this.blocks.commit();
      this.sizeDirty = true;
      this.updateRunning();
    });
  }

  private updateRunning(): void {
    if (this.disposed) return;
    if (this.pageVisible && this.mountVisible) this.start();
    else this.stop();
  }

  private start(): void {
    if (this.running || this.disposed || !this.pageVisible || !this.mountVisible) return;
    this.running = true;
    this.last = performance.now();
    this.adaptive.reset();
    this.raf = requestAnimationFrame(this.frame);
  }

  private stop(): void {
    this.running = false;
    cancelAnimationFrame(this.raf);
  }

  dispose(): void {
    if (this.disposed) return;
    this.disposed = true;
    this.stop();
    window.clearTimeout(this.lostTimer);
    for (const fn of this.cleanups) fn();
    this.labels.dispose();
    this.blocks.dispose();
    this.edges.dispose();
    this.ground.dispose();
    this.snow.dispose();
    this.bursts.dispose();
    this.trace.dispose();
    this.post.dispose();
    this.renderer.dispose();
    this.renderer.forceContextLoss();
    this.canvas.remove();
    this.opts.mount.classList.remove("hover");
    this.opts.mount.removeAttribute("title");
    if (this.opts.debug) delete (window as unknown as { __fxScene?: unknown }).__fxScene;
  }

  // ------------------------------------------------------------------ palette and quality

  private reloadPalette(): void {
    this.palette = makePalette(readPaletteHex());
    this.applyPalette();
  }

  private applyPalette(): void {
    const p = this.palette;
    this.env.uFogColor.value.copy(p.fog);
    this.env.uHud.value.copy(p.hud);
    this.renderer.setClearColor(p.fog, 1);
    const bu = this.blocks.material.uniforms;
    (bu.uLit.value as Color).copy(p.lit);
    (bu.uShade.value as Color).copy(p.shade);
    (bu.uRim.value as Color).copy(p.rim);
    (this.blocks.shadowMaterial.uniforms.uShadow.value as Color).copy(p.shadow);
    this.blocks.shadowMaterial.uniforms.uShadowAlpha.value = p.hex.shadow.alpha;
    this.ground.uniforms.uGround.value.copy(p.ground);
    this.snow.uniforms.uSnow.value.copy(p.snow);
    this.snow.uniforms.uSnowAlpha.value = p.hex.snow.alpha;
    (this.edges.ribbonMaterial.uniforms.uFocusColor.value as Color).copy(p.glow.probe);
    (this.edges.flowMaterial.uniforms.uFocusColor.value as Color).copy(p.glow.probe);
    (this.edges.ribbonMaterial.uniforms.uPulseColor.value as Color).copy(p.glow.ice);
    this.post.bloom.threshold = p.hex.bloomThreshold;
    this.post.bloom.strength = p.hex.bloomStrength;
  }

  private applyTier(): void {
    const mode = this.opts.quality;
    this.tier = TIERS[mode === "auto" ? "high" : mode];
    const rung = mode === "auto" ? this.adaptive.current : null;
    this.post.bloomOn = rung ? rung.bloom && this.tier.bloom : this.tier.bloom;
    this.post.setSamples(this.tier.samples);
    const still = this.reducedMotion;
    const preview = this.opts.preview;
    this.snow.setCounts(still ? 0 : preview ? 260 : this.tier.snow[0], still || preview ? 0 : this.tier.snow[1]);
    this.snow.points.visible = !still;
    this.bursts.points.visible = !still;
    this.edges.setFlowCap(still ? 0 : this.tier.flow);
    this.edges.flowMaterial.uniforms.uFlowOn.value = still ? 0 : 1;
    this.tierName = mode === "auto" ? `auto:${rung?.name ?? "high"}` : mode;
    this.sizeDirty = true;
  }

  private resize(): void {
    const host = this.stage ?? this.opts.mount;
    const w = Math.max(1, host.clientWidth);
    const h = Math.max(1, host.clientHeight);
    const rung = this.opts.quality === "auto" ? this.adaptive.current : null;
    const pr = pixelRatio(w, h, window.devicePixelRatio || 1, this.tier.maxPixels, rung?.multiplier ?? 1);
    const changed = w !== this.canvasW || h !== this.canvasH || Math.abs(pr - this.pr) > 1e-3;
    this.canvasW = w;
    this.canvasH = h;
    this.pr = pr;
    this.renderer.setPixelRatio(pr);
    this.renderer.setSize(w, h, false);
    const bw = this.canvas.width;
    const bh = this.canvas.height;
    this.post.setSize(bw, bh);
    this.env.uResolution.value.set(bw, bh);
    this.env.uPixelRatio.value = pr;
    this.sizeDirty = false;
    this.rectDirty = true;
    if (changed) this.emitQuality();
  }

  private emitQuality(): void {
    if (this.opts.preview) return;
    window.dispatchEvent(new CustomEvent(QUALITY, { detail: { tier: this.tierName, pixelRatio: this.pr, fps: Math.round(this.adaptive.fps || this.stats.fps) } }));
  }

  private readRect(): void {
    const m = this.opts.mount.getBoundingClientRect();
    const c = this.stage ? this.canvas.getBoundingClientRect() : m;
    const rect: SafeRect = {
      canvasWidth: this.canvasW,
      canvasHeight: this.canvasH,
      x: m.left - c.left,
      y: m.top - c.top,
      width: Math.max(1, m.width),
      height: Math.max(1, m.height),
    };
    this.canvasLeft = c.left;
    this.canvasTop = c.top;
    const r = this.rect;
    const moved = rect.x !== r.x || rect.y !== r.y || rect.width !== r.width || rect.height !== r.height || rect.canvasWidth !== r.canvasWidth || rect.canvasHeight !== r.canvasHeight;
    this.rect = rect;
    this.rectDirty = false;
    if (moved) {
      this.rig.setRect(rect);
      this.framingKey = "";
      const stretch = this.opts.preview ? 1 : columnStretch(this.rig.aspect);
      if (Math.abs(stretch - this.stretch) > 0.01) {
        // a different panel shape lays the columns out anew: blocks, edges and the trace follow
        this.stretch = stretch;
        this.structure = "";
        this.dirty = true;
      }
    }
  }

  // ------------------------------------------------------------------ model

  private rebuild(): void {
    this.dirty = false;
    const graph = this.graph;
    const view = this.view;
    if (!graph || !view) return;
    const previous = this.model;
    const model = sceneModel(graph, view, previous ?? undefined);
    this.model = model;
    this.ruled = ruledOut(view);
    this.path = incidentPath(model, view);

    const structure = `${model.nodes.map((n) => n.id).join(",")}|${model.links.map((l) => l.id).join(",")}`;
    const moved = structure !== this.structure;
    if (moved) {
      this.structure = structure;
      this.placed = layout(graph, this.stretch);
      this.rebuildStructure(model);
    }
    this.nodes = model.nodes;
    this.labels.setNodes(model.nodes, this.path);

    // events from the difference to the previous model
    if (previous && this.introStart >= 0) {
      const before = new Map(previous.nodes.map((n) => [n.id, n.tone]));
      for (let i = 0; i < model.nodes.length; i++) {
        const n = model.nodes[i];
        const was = before.get(n.id);
        if (was === undefined) continue;
        if (ALARMED.has(n.tone) && !ALARMED.has(was)) this.crack(i);
        else if (!ALARMED.has(n.tone) && ALARMED.has(was)) this.refreeze(i);
      }
      if (model.ticks > previous.ticks) {
        const c = this.ground.uniforms.uCenter.value;
        this.ground.pulse("tick", c.x, c.y, this.time, this.palette.hud);
      }
      if (model.added.length) this.freezeIn(model.added);
    }

    // a test result runs as a pulse along its edge
    const changes = view.edgeChanges.length;
    if (changes < this.edgeChanges) this.edgeChanges = 0;
    for (let c = this.edgeChanges; c < changes; c++) {
      const edge = view.edgeChanges[c].edge;
      for (let i = 0; i < model.links.length; i++) {
        if (model.links[i].id.startsWith(`${edge}:`)) {
          const lv = this.linkVisuals[i];
          if (lv) {
            lv.pending = true;
            lv.pulse = this.time + (c - this.edgeChanges) * 0.035;
          }
        }
      }
    }
    this.edgeChanges = changes;

    if (model.phase === "verdict" && previous?.phase !== "verdict") this.verdictAt = this.time;
    this.trace.set(model.trace, (id) => {
      if (!this.placed.has(id)) return undefined;
      const v = this.top(id, this.tmpV);
      return [v.x, v.y, v.z];
    }, moved);
    this.labels.setMarkers(this.trace.markers);
  }

  private rebuildStructure(model: SceneModel): void {
    const nodes = model.nodes;
    this.nodeIndex = new Map(nodes.map((n, i) => [n.id, i]));
    for (const n of nodes) {
      if (this.visuals.has(n.id)) continue;
      const waiting = this.introStart < 0;
      this.visuals.set(n.id, {
        core: this.palette.glow.ice.clone(),
        glow: 0.3,
        crack: ALARMED.has(n.tone) ? 1 : 0,
        dim: 0,
        highlight: 0,
        flash: 0,
        shake: 0,
        path: 0,
        seed: hash(n.id),
        start: waiting ? -1 : this.time,
        duration: waiting ? 0 : this.introDuration > 0 ? FREEZE_IN : 0,
        m: 0,
      });
    }
    for (const id of [...this.visuals.keys()]) if (!this.nodeIndex.has(id)) this.visuals.delete(id);
    this.blocks.count = nodes.length;
    for (let i = 0; i < nodes.length; i++) {
      const s = i * 4;
      this.blocks.state2[s + 2] = this.visuals.get(nodes[i].id)?.seed ?? 0;
      this.blocks.state2[s + 3] = nodes[i].kind === "log" ? 1 : 0;
    }

    // keep link state by id
    const old = new Map(this.linkIds.map((id, i) => [id, this.linkVisuals[i]]));
    this.linkIds = model.links.map((l) => l.id);
    this.linkVisuals = model.links.map((l) => old.get(l.id) ?? { focus: 0, path: 0, reveal: 0, pulse: -100, pending: false });
    this.edges.setLinks(model.links, (id) => this.box(id), this.reducedMotion ? 0 : this.tier.flow);

    // ground framing of the whole graph
    let minX = Infinity;
    let maxX = -Infinity;
    let minZ = Infinity;
    let maxZ = -Infinity;
    for (const p of this.placed.values()) {
      minX = Math.min(minX, p.position[0]);
      maxX = Math.max(maxX, p.position[0]);
      minZ = Math.min(minZ, p.position[2]);
      maxZ = Math.max(maxZ, p.position[2]);
    }
    this.ground.uniforms.uCenter.value.set((minX + maxX) / 2, (minZ + maxZ) / 2);
    this.ground.uniforms.uRadius.value = Math.hypot(maxX - minX, maxZ - minZ) * 0.5 + 2;
    if (this.ringCenter.lengthSq() === 0) this.ringCenter.copy(this.ground.uniforms.uCenter.value);
  }

  private box(id: string): BlockBox | undefined {
    const p = this.placed.get(id);
    return p ? { center: p.position, scale: p.scale } : undefined;
  }

  /** The point on top of block `id`. */
  private top(id: string, out: Vector3): Vector3 {
    const p = this.placed.get(id);
    if (!p) return out.set(0, 0, 0);
    return out.set(p.position[0], p.position[1] + (BLOCK[1] * p.scale[1]) / 2, p.position[2]);
  }

  private readonly labelAnchor = (i: number, out: Vector3): Vector3 => {
    this.top(this.nodes[i].id, out);
    out.y += 0.02;
    return out;
  };

  private readonly labelVisible = (i: number): boolean => (this.visuals.get(this.nodes[i].id)?.m ?? 0) > 0.92;

  // ------------------------------------------------------------------ events

  private requestIntro(seconds: number): void {
    if (this.introStart >= 0) return;
    if (!this.ready) {
      this.pendingIntro = seconds;
      return;
    }
    this.startIntro(seconds);
  }

  private startIntro(seconds: number): void {
    const duration = this.reducedMotion ? 0 : seconds;
    this.introStart = this.time;
    this.introDuration = duration;
    const columns = [...this.placed.values()].map((p) => p.column);
    const lo = Math.min(...columns);
    const span = Math.max(1, Math.max(...columns) - lo);
    for (let i = 0; i < this.nodes.length; i++) {
      const v = this.visuals.get(this.nodes[i].id);
      const p = this.placed.get(this.nodes[i].id);
      if (!v || !p) continue;
      const delay = duration * (0.08 + 0.5 * ((p.column - lo) / span) + 0.06 * v.seed);
      v.start = this.time + delay;
      v.duration = duration * 0.4;
      if (duration > 0.5) this.bursts.motes(p.position[0], p.position[1], p.position[2], v.start - v.duration * 0.15, v.duration * 0.85, 12, this.palette.hud);
    }
    if (duration <= 0) {
      for (const lv of this.linkVisuals) lv.reveal = 1;
    }
  }

  private crack(i: number): void {
    const v = this.visuals.get(this.nodes[i].id);
    const p = this.placed.get(this.nodes[i].id);
    if (!v || !p) return;
    v.shake = 1;
    if (this.reducedMotion) return;
    this.bursts.shards(p.position[0], p.position[1], p.position[2], this.time, 150, this.palette.glow.alarm, this.palette.hud);
    this.ground.pulse("alarm", p.position[0], p.position[2], this.time, this.palette.glow.alarm);
  }

  private refreeze(i: number): void {
    const v = this.visuals.get(this.nodes[i].id);
    const p = this.placed.get(this.nodes[i].id);
    if (!v || !p) return;
    v.flash = 1;
    this.ground.pulse("freeze", p.position[0], p.position[2], this.time, this.palette.glow.ice);
  }

  private freezeIn(ids: string[]): void {
    this.visitIds = [];
    for (const id of ids) {
      const v = this.visuals.get(id);
      const p = this.placed.get(id);
      if (!v || !p) continue;
      v.start = this.time;
      v.duration = this.reducedMotion ? 0 : FREEZE_IN;
      v.m = 0;
      this.fresh.set(id, this.time);
      this.labels.setFresh(id, true);
      this.visitIds.push(id);
      if (!this.reducedMotion) {
        this.bursts.motes(p.position[0], p.position[1], p.position[2], this.time, FREEZE_IN * 0.8, 22, this.palette.glow.ice);
        this.ground.pulse("freeze", p.position[0], p.position[2], this.time + FREEZE_IN * 0.6, this.palette.glow.ice);
      }
    }
    // the camera visits the new metric with its neighbours
    const model = this.model;
    if (model && this.visitIds.length) {
      const near = new Set(this.visitIds);
      for (const l of model.links) {
        if (near.has(l.source)) near.add(l.target);
        else if (near.has(l.target)) near.add(l.source);
      }
      this.visitIds = [...near];
      this.visitUntil = this.time + VISIT;
    }
  }

  // ------------------------------------------------------------------ picking

  /** Index of the block under a client point, or -1. */
  private pick(clientX: number, clientY: number): number {
    this.readRect();
    return this.pickCanvas(clientX - this.canvasLeft, clientY - this.canvasTop);
  }

  /** Index of the block under a point in canvas CSS pixels, or -1. */
  private pickCanvas(x: number, y: number): number {
    if (!this.nodes.length) return -1;
    const cam = this.rig.camera;
    this.ndc.set((x / this.canvasW) * 2 - 1, -((y / this.canvasH) * 2 - 1));
    const o = cam.position;
    this.rayDir.set(this.ndc.x, this.ndc.y, 0.5).unproject(cam).sub(o).normalize();
    let best = -1;
    let bestT = Infinity;
    for (let i = 0; i < this.nodes.length; i++) {
      const p = this.placed.get(this.nodes[i].id);
      const v = this.visuals.get(this.nodes[i].id);
      if (!p || !v || v.m < 0.5) continue;
      const t = slab(
        o,
        this.rayDir,
        p.position[0],
        p.position[1],
        p.position[2],
        (BLOCK[0] * p.scale[0]) / 2 + 0.06,
        (BLOCK[1] * p.scale[1]) / 2 + 0.06,
        (BLOCK[2] * p.scale[2]) / 2 + 0.06,
      );
      if (t >= 0 && t < bestT) {
        bestT = t;
        best = i;
      }
    }
    return best;
  }

  private updateHover(): void {
    if (!this.pointerDirty) return;
    this.pointerDirty = false;
    let hit = -1;
    if (this.pointerClient) hit = this.pickCanvas(this.pointerClient.x - this.canvasLeft, this.pointerClient.y - this.canvasTop);
    if (hit === this.hover) return;
    this.hover = hit;
    this.labels.setHover(hit >= 0 ? this.nodes[hit].id : null);
    const mount = this.opts.mount;
    mount.classList.toggle("hover", hit >= 0);
    if (hit >= 0 && this.graph) mount.title = nodeTitle(this.graph, this.nodes[hit]);
    else mount.removeAttribute("title");
  }

  // ------------------------------------------------------------------ frame

  private readonly frame = (now: number): void => {
    if (!this.running) return;
    this.raf = requestAnimationFrame(this.frame);
    try {
      this.step(now);
    } catch (error) {
      this.stop();
      this.opts.onFail(error instanceof Error ? error : new Error(String(error)));
    }
  };

  private step(now: number): void {
    const cpu = performance.now();
    const raw = (now - this.last) / 1000;
    this.last = now;
    const dt = Math.min(Math.max(raw, 0), 0.1);
    this.time += dt;
    this.env.uTime.value = this.time;
    this.frames += 1;

    if (this.opts.quality === "auto" && this.frames > 1 && this.adaptive.sample(raw)) {
      this.applyTier();
    }
    if (this.sizeDirty) this.resize();
    if (this.rectDirty || this.frames % 30 === 0) this.readRect();
    if (this.dirty) this.rebuild();

    // the intro cue, or the scene's own start when the cue does not come
    if (this.ready && this.introStart < 0) {
      if (this.opts.preview) this.startIntro(1.2);
      else if (this.pendingIntro !== null) this.startIntro(this.pendingIntro);
      else if (this.time - this.readyAt > INTRO_WAIT) this.startIntro(this.opts.skipIntro ? 0 : DEFAULT_INTRO);
    }

    this.updateHover();
    if (this.fresh.size && this.frames % 30 === 0) {
      for (const [id, at] of this.fresh) {
        if (this.time - at < FRESH) continue;
        this.fresh.delete(id);
        this.labels.setFresh(id, false);
      }
    }
    this.animateNodes(dt);
    this.animateLinks(dt);
    this.aim(dt);

    const introT = this.introStart < 0 ? 0 : this.introDuration <= 0 ? 1 : (this.time - this.introStart) / this.introDuration;
    const lift = 1 - easeOut(introT);
    const d = this.rig.distance;
    this.env.uFogNear.value = d * 0.72;
    this.env.uFogDensity.value = (0.85 / Math.max(d, 1)) * (1 + 2.2 * lift);

    // the walk matters while Argus investigates; once the verdict is in, the lit path tells the story
    const phase = this.model?.phase;
    const traceAlpha = !this.model?.trace.length || this.opts.preview ? 0 : phase === "investigating" || phase === "anomaly" ? 0.85 : 0.3;
    const drawn = this.trace.update(dt, traceAlpha * (this.introStart >= 0 ? 1 : 0), this.reducedMotion);

    this.updateParticles();
    this.bursts.commit();
    this.blocks.commit();
    this.edges.commit();

    this.renderer.info.reset();
    const fringe = this.tier.fringe && !this.reducedMotion ? Math.min(3, Math.max(0, this.rig.speed - 0.08) * 6) * this.pr : 0;
    this.post.render(this.renderer, this.scene, this.rig.camera, fringe, this.time);

    this.updateLabels(drawn, traceAlpha > 0);

    if (!this.ready) {
      this.ready = true;
      this.readyAt = this.time;
      this.canvas.classList.toggle("live", this.mountVisible);
      if (!this.opts.preview) {
        window.dispatchEvent(new CustomEvent(SCENE_READY));
        this.emitQuality();
      }
    }
    this.measure(raw, performance.now() - cpu);
  }

  private animateNodes(dt: number): void {
    const model = this.model;
    if (!model) return;
    const pal = this.palette;
    const t = this.time;
    const anomaly = this.view ? currentInvestigation(this.view)?.anomaly.node : undefined;
    for (let i = 0; i < this.nodes.length; i++) {
      const n = this.nodes[i];
      const v = this.visuals.get(n.id);
      const p = this.placed.get(n.id);
      if (!v || !p) continue;

      // materialize
      if (v.start >= 0) v.m = v.duration <= 0 ? 1 : ease((t - v.start) / v.duration);
      else v.m = 0;

      // targets from the state
      let glow = 0.3;
      let tint = pal.glow.ice;
      if (n.kind === "log") {
        glow = 0.16;
      } else {
        switch (n.tone) {
          case "wiggle":
            tint = pal.glow.watch;
            glow = 0.85;
            break;
          case "symptom":
            tint = pal.glow.alarm;
            glow = 0.75;
            break;
          case "alarm":
            tint = pal.glow.alarm;
            glow = 1.9;
            break;
          case "root":
            tint = pal.glow.alarm;
            glow = 2.3;
            break;
          case "resolved":
            tint = pal.glow.ok;
            glow = 0.95;
            break;
          default:
            break;
        }
        if (!n.scored && !n.focus) glow *= 0.7;
      }
      this.tmpColor.copy(tint);
      if (n.heat > 0.02 && n.tone === "normal") {
        this.tmpColor.lerp(pal.glow.watch, Math.min(1, n.heat * 0.8));
        glow += n.heat * 0.9;
      }
      const pathOn = this.path.size > 0;
      const inPath = this.path.has(n.id);
      if (inPath && !ALARMED.has(n.tone)) {
        // what the anomaly moves glows warm; the evidence that held glows like the probe
        this.tmpColor.lerp(n.kind === "log" ? pal.glow.probe : pal.glow.alarm, n.kind === "log" ? 0.8 : 0.45);
        glow = Math.max(glow, 1.15);
      }
      if (n.focus) {
        if (!ALARMED.has(n.tone)) this.tmpColor.lerp(pal.glow.probe, 0.8);
        glow = Math.max(glow, 1.45);
      }
      const recede = pathOn && !inPath && !n.focus ? 0.92 : 0;
      const quiet = n.kind === "metric" && !n.northStar && !inPath && !n.focus && n.tone === "normal" ? 0.3 : 0;
      glow *= 1 - 0.75 * recede;
      v.path = approach(v.path, inPath ? 1 : 0, 4, dt);
      v.core.lerp(this.tmpColor, 1 - Math.exp(-6 * dt));
      v.glow = approach(v.glow, glow, 6, dt);
      const crack = ALARMED.has(n.tone) ? 1 : n.tone === "symptom" ? 0.3 : 0;
      v.crack = crack > v.crack ? Math.min(crack, v.crack + dt / 0.35) : Math.max(crack, v.crack - dt / 1.4);
      v.dim = approach(v.dim, Math.max(this.ruled.has(n.id) && n.id !== anomaly ? 1 : 0, recede, quiet), 3, dt);
      v.highlight = approach(v.highlight, i === this.hover ? 1 : n.focus ? 0.55 : inPath ? 0.5 : 0, 10, dt);
      v.flash = Math.max(0, v.flash - dt / 1.3);
      v.shake = Math.max(0, v.shake - dt / 0.6);

      const bob = this.reducedMotion ? 0 : Math.sin(t * 0.7 + v.seed * 6.3) * 0.022;
      const jolt = v.shake * v.shake * 0.05 * Math.sin(t * 61 + v.seed * 9);
      const grow = 0.94 + 0.06 * v.m;
      this.blocks.place(i, p.position[0] + jolt, p.position[1] + bob, p.position[2], p.scale[0] * grow, p.scale[1] * grow, p.scale[2] * grow);
      const c = i * 3;
      this.blocks.core[c] = v.core.r;
      this.blocks.core[c + 1] = v.core.g;
      this.blocks.core[c + 2] = v.core.b;
      const s = i * 4;
      this.blocks.state[s] = v.glow;
      this.blocks.state[s + 1] = v.crack;
      this.blocks.state[s + 2] = v.m;
      this.blocks.state[s + 3] = v.dim;
      this.blocks.state2[s] = v.highlight;
      this.blocks.state2[s + 1] = v.flash;
    }
  }

  private animateLinks(dt: number): void {
    const model = this.model;
    if (!model) return;
    const pal = this.palette;
    const d = this.edges.data;
    for (let i = 0; i < model.links.length && i < this.edges.count; i++) {
      const link = model.links[i];
      const lv = this.linkVisuals[i];
      const a = this.visuals.get(link.source);
      const b = this.visuals.get(link.target);
      const ready = Math.min(a?.m ?? 0, b?.m ?? 0);
      if (ready >= 0.98) lv.reveal = Math.min(1, lv.reveal + dt / 0.7);
      else lv.reveal = Math.min(lv.reveal, ready);
      if (lv.pending && lv.reveal >= 1) {
        lv.pending = false;
        lv.pulse = Math.max(lv.pulse, this.time);
      }
      lv.focus = approach(lv.focus, link.focus ? 1 : 0, 8, dt);
      const onPath = this.path.has(link.source) && this.path.has(link.target);
      lv.path = approach(lv.path, onPath ? 1 : 0, 4, dt);
      const si = this.nodeIndex.get(link.source);
      const ti = this.nodeIndex.get(link.target);
      const sStar = si !== undefined && this.nodes[si]?.northStar;
      const tStar = ti !== undefined && this.nodes[ti]?.northStar;
      const hovered = this.hover >= 0 && (si === this.hover || ti === this.hover) ? 1 : 0;

      let swatch: keyof PaletteHex["edge"] = "valid";
      if (link.kind === "definition") swatch = "definition";
      else if (link.status === "SUPPORTED") swatch = "supported";
      else if (link.status === "PROBATION") swatch = "probation";
      else if (link.status === "PROPOSED") swatch = "proposed";
      else if (link.status === "BROKEN") swatch = "broken";
      // the path burns warm; with a path on screen everything else recedes; ratio definitions and links
      // between quiet metrics stay faint unless they are hovered, checked or on the path
      const col = this.tmpColor.copy(pal.edge[swatch]).lerp(pal.glow.alarm, lv.path * 0.7);
      let alpha = pal.hex.edge[swatch].alpha;
      if (link.kind === "definition") alpha *= Math.max(lv.focus, lv.path, hovered) * 0.9;
      else if (!sStar && !tStar) alpha *= Math.max(0.45, hovered);
      if (this.path.size > 0) alpha *= 0.22 + 0.78 * Math.max(lv.path, lv.focus);
      alpha = Math.max(alpha, lv.path, hovered * 0.8);
      let o = this.edges.at(i, 2);
      d[o + 3] = WIDTH[link.kind] + lv.path * 1.5 + (sStar && tStar ? 0.5 : 0);
      o = this.edges.at(i, 3);
      d[o + 3] = lv.reveal;
      o = this.edges.at(i, 4);
      d[o] = col.r;
      d[o + 1] = col.g;
      d[o + 2] = col.b;
      d[o + 3] = alpha;
      o = this.edges.at(i, 5);
      d[o] = lv.focus;
      d[o + 1] = lv.pending ? -100 : lv.pulse;
      d[o + 2] = link.status === "BROKEN" ? 1 : 0;
      d[o + 3] = link.status === "PROPOSED" ? 1 : 0;
    }
  }

  /** Where the camera looks: the overview, the investigation, the verdict or a newly learned metric. */
  private aim(dt: number): void {
    const model = this.model;
    const view = this.view;
    let ids: string[] = [];
    let mode = "overview";
    if (model && view && !this.reducedMotion && this.introStart >= 0) {
      const investigation = currentInvestigation(view);
      if (this.opts.preview) {
        if (this.path.size) {
          mode = "path";
          ids = [...this.path];
        }
      } else if (this.time < this.visitUntil) {
        mode = "visit";
        ids = this.visitIds;
      } else if (investigation && (model.phase === "anomaly" || model.phase === "investigating")) {
        mode = "investigation";
        const set = new Set<string>([investigation.anomaly.node]);
        for (const t of model.trace) set.add(t.id);
        for (const id of view.focus?.nodes ?? []) set.add(id);
        for (const id of view.focus?.logs ?? []) set.add(id);
        ids = [...set];
      } else if (model.phase === "verdict" && this.time - this.verdictAt < VERDICT_HOLD) {
        mode = "verdict";
        ids = [...new Set([...this.path, ...model.trace.map((t) => t.id)])];
      }
    }
    ids = ids.filter((id) => this.placed.has(id));
    if (!ids.length) mode = "overview";
    const key = `${mode}:${ids.join(",")}:${this.structure.length}`;
    if (key !== this.framingKey && this.placed.size) {
      this.framingKey = key;
      this.cameraMode = mode;
      const list = mode === "overview" ? [...this.placed.keys()] : ids;
      const pts: number[] = [];
      for (const id of list) {
        const p = this.placed.get(id);
        if (!p) continue;
        const hx = (BLOCK[0] * p.scale[0]) / 2;
        const hy = (BLOCK[1] * p.scale[1]) / 2;
        const hz = (BLOCK[2] * p.scale[2]) / 2;
        for (let k = 0; k < 8; k++) {
          pts.push(p.position[0] + (k & 1 ? hx : -hx), p.position[1] + (k & 2 ? hy + (mode === "overview" ? 0.3 : 0.9) : -hy), p.position[2] + (k & 4 ? hz : -hz));
        }
      }
      if (mode === "overview") this.rig.target(pts, 0.05, 0);
      else this.rig.target(pts, mode === "path" ? 0.1 : 0.16, mode === "visit" ? 20 : mode === "path" ? 12 : 17);
    }
    if (this.introStart < 0) this.rig.intro = 1;
    else this.rig.intro = this.introDuration <= 0 ? 0 : 1 - ease((this.time - this.introStart) / (this.introDuration * 1.15));
    this.rig.update(dt, this.pointerWindow, this.reducedMotion);

    // rings center on what is being checked
    const focus = view?.focus;
    const anomaly = view ? currentInvestigation(view)?.anomaly.node : undefined;
    const ringIds = [...(focus?.logs ?? []), ...(focus?.nodes ?? [])];
    let target: Placement | undefined;
    for (const id of ringIds) {
      target = this.placed.get(id);
      if (target) break;
    }
    if (!target && anomaly && model && model.phase !== "resolved" && model.phase !== "idle") target = this.placed.get(anomaly);
    const g = this.ground.uniforms;
    if (target) {
      const k = 1 - Math.exp(-5 * dt);
      this.ringCenter.x += (target.position[0] - this.ringCenter.x) * k;
      this.ringCenter.y += (target.position[2] - this.ringCenter.y) * k;
    }
    g.uRingCenter.value.copy(this.ringCenter);
    g.uRings.value = approach(g.uRings.value, target ? 1 : 0, 3, dt);
  }

  private updateParticles(): void {
    const s = this.snow.uniforms;
    s.uCenter.value.copy(this.rig.center);
    const cam = this.rig.camera.position;
    s.uNearCenter.value.copy(cam).lerp(this.rig.center, 0.3);
    if (this.pointerClient && !this.reducedMotion) {
      const x = this.pointerClient.x - this.canvasLeft;
      const y = this.pointerClient.y - this.canvasTop;
      s.uPointer.value.set((x / this.canvasW) * 2 - 1, -((y / this.canvasH) * 2 - 1));
      s.uPointerOn.value = 1;
    } else s.uPointerOn.value = 0;
  }

  private updateLabels(drawn: number, traceOn: boolean): void {
    const boxes = this.focusBoxes;
    boxes.length = 0;
    for (let i = 0; i < this.nodes.length && boxes.length < this.boxPool.length; i++) {
      const n = this.nodes[i];
      if (!n.focus && i !== this.hover) continue;
      const p = this.placed.get(n.id);
      const v = this.visuals.get(n.id);
      if (!p || !v || v.m < 0.9) continue;
      const b = this.boxPool[boxes.length];
      b.center.set(p.position[0], p.position[1], p.position[2]);
      b.half.set((BLOCK[0] * p.scale[0]) / 2, (BLOCK[1] * p.scale[1]) / 2, (BLOCK[2] * p.scale[2]) / 2);
      b.hover = i === this.hover && !n.focus;
      boxes.push(b);
    }
    const r = this.rect;
    this.labels.update(
      this.rig.camera,
      this.nodes,
      this.labelAnchor,
      this.labelVisible,
      boxes,
      this.trace.markers,
      drawn,
      traceOn,
      this.canvasW,
      this.canvasH,
      r.x,
      r.y,
      r.width,
      r.height,
      this.rig.center,
    );
  }

  private measure(raw: number, cpuMs: number): void {
    this.statFrames += 1;
    this.statTime += raw;
    this.statWorst = Math.max(this.statWorst, raw * 1000);
    if (this.statTime < 1) return;
    const info = this.renderer.info.render;
    this.stats = {
      fps: this.statFrames / this.statTime,
      worstMs: this.statWorst,
      cpuMs,
      calls: info.calls,
      triangles: info.triangles,
      points: info.points,
      pixelRatio: this.pr,
      width: this.canvas.width,
      height: this.canvas.height,
      tier: this.tierName,
      bloom: this.post.bloomOn,
      camera: this.cameraMode,
    };
    this.statFrames = 0;
    this.statTime = 0;
    this.statWorst = 0;
    // the first measured second gives the layer's readout a real frame rate instead of the 0 sent at start
    if (!this.measured) {
      this.measured = true;
      this.emitQuality();
    }
    if (this.opts.debug) (window as unknown as { __fxScene?: SceneStats }).__fxScene = this.stats;
  }
}

/** Ray against an axis-aligned box: distance along the ray, or -1. */
const NEAR = { t: 0 };
const FAR = { t: 0 };

function slab(o: Vector3, d: Vector3, cx: number, cy: number, cz: number, hx: number, hy: number, hz: number): number {
  NEAR.t = -Infinity;
  FAR.t = Infinity;
  if (!axis(o.x, d.x, cx - hx, cx + hx, NEAR, FAR)) return -1;
  if (!axis(o.y, d.y, cy - hy, cy + hy, NEAR, FAR)) return -1;
  if (!axis(o.z, d.z, cz - hz, cz + hz, NEAR, FAR)) return -1;
  return FAR.t < 0 ? -1 : Math.max(NEAR.t, 0);
}

function axis(o: number, d: number, lo: number, hi: number, near: { t: number }, far: { t: number }): boolean {
  if (Math.abs(d) < 1e-9) return o >= lo && o <= hi;
  const a = (lo - o) / d;
  const b = (hi - o) / d;
  near.t = Math.max(near.t, Math.min(a, b));
  far.t = Math.min(far.t, Math.max(a, b));
  return near.t <= far.t;
}

function hash(id: string): number {
  let h = 2166136261;
  for (let i = 0; i < id.length; i++) {
    h ^= id.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return ((h >>> 0) % 10007) / 10007;
}
