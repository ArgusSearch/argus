// The imperative side of the village. It owns the renderer, the camera and the render loop; the page hands it
// the player (the clock and its timeline) and the folded village state, and DOM elements to keep pinned to
// the igloos (bubbles, name plates) and to the case file. React never re-renders per frame: the engine moves
// those elements itself.

import {
  Color,
  DirectionalLight,
  Fog,
  HemisphereLight,
  PCFShadowMap,
  PerspectiveCamera,
  PMREMGenerator,
  Raycaster,
  Scene,
  Vector2,
  Vector3,
  WebGLRenderer,
  type Texture,
} from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { Post } from "../../fx/scene/post";
import { AdaptiveQuality, pixelRatio, TIERS, type QualityMode, type TierSpec } from "../../fx/scene/quality";
import { placePin } from "../Overlay";
import type { Player } from "../player";
import { APPROVAL_POST, ROLE, ROLES, ROLE_IDS, type RoleId } from "../roles";
import { slotAt, TRAVEL, type VillageState } from "../timeline";
import { Bot, BOT_SIZE, CaseFile } from "./bots";
import { Igloos } from "./igloo";
import { buildRoom, SEAT, type Room } from "./rooms";
import { approach, easeInOut } from "./util";
import { route, seatPoint, World } from "./world";

export interface EngineOptions {
  mount: HTMLElement;
  player: Player;
  /** DOM elements the engine keeps over their 3D anchors: "bubble:<role>", "plate:<role>", "file" */
  anchors: Map<string, HTMLElement>;
  onSelect: (role: RoleId) => void;
  onHover: (role: RoleId | null) => void;
  quality: QualityMode;
  onFail: (error: Error) => void;
}

export interface VillageStats {
  fps: number;
  tier: string;
  pixelRatio: number;
  calls: number;
  triangles: number;
}

const FOV = 24;
/** where the camera looks from, relative to its target: elevated toward the viewer */
const VIEW = new Vector3(0, 0.78, 1).normalize();

export class VillageEngine {
  private readonly opts: EngineOptions;
  private readonly renderer: WebGLRenderer;
  private readonly canvas: HTMLCanvasElement;
  private readonly scene = new Scene();
  private readonly camera = new PerspectiveCamera(FOV, 1, 1, 200);
  private readonly post: Post;
  private readonly env: Texture;
  private readonly world: World;
  private readonly igloos: Igloos;
  private readonly rooms = new Map<RoleId, Room>();
  private readonly bots = new Map<RoleId, Bot>();
  private readonly file = new CaseFile();
  private readonly sun: DirectionalLight;
  private readonly fog: Fog;
  private readonly adaptive = new AdaptiveQuality();
  private readonly raycaster = new Raycaster();
  private readonly pointer = new Vector2(0, 0);
  private readonly target = new Vector3(0, 0.4, -0.4);
  private readonly look = new Vector3(0, 0.4, -0.4);
  private tier: TierSpec;
  private state: VillageState | null = null;
  private frame = 0;
  private last = 0;
  private time = 0;
  private distance = 40;
  private width = 1;
  private height = 1;
  private sizeDirty = true;
  private hovered: RoleId | null = null;
  private lastIndex = -1;
  private disposed = false;
  private readonly observer: ResizeObserver;
  private readonly cleanups: (() => void)[] = [];
  private readonly reduced: boolean;
  stats: VillageStats = { fps: 0, tier: "", pixelRatio: 1, calls: 0, triangles: 0 };

  constructor(opts: EngineOptions) {
    this.opts = opts;
    this.reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
    this.tier = TIERS[opts.quality === "auto" ? "high" : opts.quality];
    this.canvas = document.createElement("canvas");
    this.canvas.className = "vl-canvas";
    this.canvas.setAttribute("aria-hidden", "true");
    this.renderer = new WebGLRenderer({ canvas: this.canvas, antialias: false, alpha: false, stencil: false, powerPreference: "high-performance" });
    this.renderer.autoClear = false;
    this.renderer.info.autoReset = false;
    this.renderer.shadowMap.enabled = true;
    this.renderer.shadowMap.type = PCFShadowMap;
    opts.mount.prepend(this.canvas);

    const fog = new Color("#a9b0be");
    this.scene.background = fog;
    this.fog = new Fog(fog, 70, 120);
    this.scene.fog = this.fog;
    this.renderer.setClearColor(fog, 1);

    const pmrem = new PMREMGenerator(this.renderer);
    this.env = pmrem.fromScene(new RoomEnvironment(), 0.04).texture;
    pmrem.dispose();

    const hemi = new HemisphereLight("#eaf1fd", "#97a1b5", 0.78);
    this.sun = new DirectionalLight("#fff6ec", 1.32);
    this.sun.position.set(-14, 22, 12);
    this.sun.target.position.set(0, 0, 0);
    this.sun.castShadow = true;
    this.sun.shadow.mapSize.set(2048, 2048);
    const cam = this.sun.shadow.camera;
    cam.left = -18;
    cam.right = 18;
    cam.top = 16;
    cam.bottom = -16;
    cam.near = 1;
    cam.far = 70;
    this.sun.shadow.bias = -0.0006;
    this.sun.shadow.normalBias = 0.03;
    this.scene.add(hemi, this.sun, this.sun.target);

    this.world = new World();
    this.igloos = new Igloos(ROLES, this.env);
    this.scene.add(this.world.group, this.igloos.group);
    for (const it of this.igloos.items) {
      const room = buildRoom(it.role.id, it.role.color);
      it.group.add(room.group);
      this.rooms.set(it.role.id, room);
    }
    const dpr = Math.min(2, window.devicePixelRatio || 1);
    ROLE_IDS.forEach((id, i) => {
      const bot = new Bot(id, 0.13 + i * 0.137, dpr);
      bot.sprite.position.copy(seatPoint(id));
      this.bots.set(id, bot);
      this.scene.add(bot.sprite);
    });
    this.scene.add(this.file.group);

    this.post = new Post(this.tier.samples);
    this.post.bloom.threshold = 1.15;
    this.post.bloom.strength = 0.45;
    this.post.bloom.radius = 0.7;
    this.applyTier();

    this.observer = new ResizeObserver(() => (this.sizeDirty = true));
    this.observer.observe(opts.mount);
    const on = <K extends keyof HTMLElementEventMap>(el: HTMLElement, type: K, fn: (e: HTMLElementEventMap[K]) => void) => {
      el.addEventListener(type, fn as EventListener);
      this.cleanups.push(() => el.removeEventListener(type, fn as EventListener));
    };
    on(opts.mount, "pointermove", (e) => {
      const r = opts.mount.getBoundingClientRect();
      this.pointer.set(((e.clientX - r.left) / r.width) * 2 - 1, -((e.clientY - r.top) / r.height) * 2 + 1);
      const hit = this.pick();
      if (hit !== this.hovered) {
        this.hovered = hit;
        opts.mount.style.cursor = hit ? "pointer" : "";
        opts.onHover(hit);
      }
    });
    on(opts.mount, "pointerleave", () => {
      this.pointer.set(0, 0);
      if (this.hovered) {
        this.hovered = null;
        opts.mount.style.cursor = "";
        opts.onHover(null);
      }
    });
    on(opts.mount, "click", (e) => {
      if ((e.target as HTMLElement).closest("button, a, [data-no-pick]")) return;
      const hit = this.pick();
      if (hit) opts.onSelect(hit);
    });
    const lost = (e: Event) => {
      e.preventDefault();
      this.stop();
      opts.onFail(new Error("WebGL context lost"));
    };
    this.canvas.addEventListener("webglcontextlost", lost);
    this.cleanups.push(() => this.canvas.removeEventListener("webglcontextlost", lost));
    const vis = () => (document.hidden ? this.stop() : this.start());
    document.addEventListener("visibilitychange", vis);
    this.cleanups.push(() => document.removeEventListener("visibilitychange", vis));
    this.start();
  }

  setState(state: VillageState): void {
    this.state = state;
    for (const id of ROLE_IDS) {
      const r = state.roles[id];
      this.bots.get(id)?.setStatus(r.status === "working" ? "working" : r.status === "waiting" ? "waiting" : "idle");
    }
  }

  start(): void {
    if (this.frame || this.disposed) return;
    this.last = performance.now();
    this.adaptive.reset();
    const loop = (now: number) => {
      this.frame = requestAnimationFrame(loop);
      const dt = Math.min(0.1, Math.max(0, (now - this.last) / 1000));
      this.last = now;
      try {
        this.render(dt);
      } catch (error) {
        this.stop();
        this.opts.onFail(error as Error);
      }
    };
    this.frame = requestAnimationFrame(loop);
  }

  stop(): void {
    if (this.frame) cancelAnimationFrame(this.frame);
    this.frame = 0;
  }

  dispose(): void {
    this.disposed = true;
    this.stop();
    this.observer.disconnect();
    for (const c of this.cleanups) c();
    for (const r of this.rooms.values()) r.dispose();
    for (const b of this.bots.values()) b.dispose();
    this.file.dispose();
    this.igloos.dispose();
    this.world.dispose();
    this.post.dispose();
    this.env.dispose();
    this.renderer.dispose();
    this.canvas.remove();
  }

  // ---------------------------------------------------------------- frame

  private applyTier(): void {
    const mode = this.opts.quality;
    this.tier = TIERS[mode === "auto" ? "high" : mode];
    const rung = mode === "auto" ? this.adaptive.current : null;
    this.post.bloomOn = rung ? rung.bloom && this.tier.bloom : this.tier.bloom;
    this.post.setSamples(this.tier.samples);
    const lowShadows = this.tier === TIERS.low || (rung && rung.multiplier < 0.9);
    this.sun.castShadow = !lowShadows;
    this.world.setSnow(this.reduced ? 0 : Math.round(this.tier.snow[0] * 1.2));
    this.stats.tier = mode === "auto" ? `auto:${rung?.name ?? "high"}` : mode;
    this.sizeDirty = true;
  }

  private resize(): void {
    const w = Math.max(1, this.opts.mount.clientWidth);
    const h = Math.max(1, this.opts.mount.clientHeight);
    const rung = this.opts.quality === "auto" ? this.adaptive.current : null;
    const pr = pixelRatio(w, h, window.devicePixelRatio || 1, this.tier.maxPixels, rung?.multiplier ?? 1);
    this.width = w;
    this.height = h;
    this.renderer.setPixelRatio(pr);
    this.renderer.setSize(w, h, false);
    this.post.setSize(this.canvas.width, this.canvas.height);
    this.camera.aspect = w / h;
    // frame the plateau: about 33 units wide and 26 deep must fit
    const halfV = Math.tan(((FOV / 2) * Math.PI) / 180);
    const fitW = 13.2 / (halfV * this.camera.aspect);
    const fitH = 9.1 / halfV;
    this.distance = Math.max(fitW, fitH);
    // the plateau stays clear; only what lies beyond it fades into the fog
    this.fog.near = this.distance + 14;
    this.fog.far = this.distance + 70;
    this.camera.near = Math.max(1, this.distance - 30);
    this.camera.far = this.distance + 120;
    this.camera.updateProjectionMatrix();
    this.stats.pixelRatio = pr;
    this.sizeDirty = false;
  }

  private pick(): RoleId | null {
    this.raycaster.setFromCamera(this.pointer, this.camera);
    const hits = this.raycaster.intersectObjects(
      this.igloos.items.map((i) => i.hit),
      false,
    );
    return (hits[0]?.object.userData.role as RoleId | undefined) ?? null;
  }

  private render(dt: number): void {
    if (this.sizeDirty) this.resize();
    if (this.opts.quality === "auto" && this.adaptive.sample(dt)) this.applyTier();
    this.time += this.reduced ? 0 : dt;
    const player = this.opts.player;
    const tl = player.timeline;
    const t = player.time;
    const state = this.state;

    // who walks where, carrying what
    const index = slotAt(tl, t);
    const walking = new Map<RoleId, { pos: Vector3; carrying: boolean }>();
    for (let i = Math.max(0, index - 4); i <= index; i++) {
      const slot = tl.slots[i];
      if (!slot?.from) continue;
      const local = t - slot.start;
      const from = slot.from;
      const to = slot.beat.role;
      if (local < TRAVEL) walking.set(from, { pos: route(from, to).getPointAt(easeInOut(local / TRAVEL)), carrying: true });
      else if (local < 2 * TRAVEL && !walking.has(from)) walking.set(from, { pos: route(to, from).getPointAt(easeInOut((local - TRAVEL) / TRAVEL)), carrying: false });
    }
    if (index !== this.lastIndex) {
      const slot = tl.slots[index];
      if (slot?.from) {
        const ig = this.igloos.items.find((it) => it.role.id === slot.beat.role);
        if (ig) ig.flash = 1;
      }
      this.lastIndex = index;
    }

    // bots: at their seat unless walking; busy ones paint every frame
    const levels = new Map<string, number>();
    for (const [id, bot] of this.bots) {
      const walk = walking.get(id);
      const home = seatPoint(id);
      const st = state?.roles[id];
      const busy = Boolean(walk) || st?.status === "working" || st?.status === "waiting";
      if (walk) {
        bot.sprite.position.copy(walk.pos);
        if (bot.status !== "working") bot.setStatus("working");
      } else {
        bot.sprite.position.lerp(home, 1 - Math.exp(-10 * dt));
        const want = st?.status === "working" ? "working" : st?.status === "waiting" ? "waiting" : "idle";
        if (bot.status !== want) bot.setStatus(want);
      }
      bot.update(dt, busy);
      levels.set(id, st?.status === "working" ? 1 : st?.status === "waiting" ? 0.85 : 0.3);
    }
    this.igloos.update(dt, levels, this.time);
    for (const [id, room] of this.rooms) room.tick(this.time, state?.roles[id].status === "working");

    // the case file
    const slot = tl.slots[index];
    const carrier = [...walking.entries()].find(([, w]) => w.carrying);
    const gate = Boolean(state?.gate);
    if (carrier) {
      const p = carrier[1].pos.clone().add(new Vector3(0.32, BOT_SIZE * 0.42, 0.3));
      this.file.place(p, 0.25 + Math.sin(this.time * 9) * 0.05, 1);
      this.file.setColor("#7cc4ff", 2);
    } else if (slot?.beat.caseId && !(slot.beat.kind === "lifecycle" && slot.beat.done.endsWith("closed"))) {
      const id = slot.beat.role;
      const r = ROLE[id];
      const desk = new Vector3(r.x - 0.62, SEAT.deskTop + 0.09 + Math.sin(this.time * 2) * 0.03, r.z + SEAT.desk.z - 0.05);
      this.file.place(desk, 0, 1);
      this.file.setColor(gate ? "#ff8a6a" : slot.beat.outcome === "alarm" ? "#ff7a6a" : "#7cc4ff", gate ? 2.2 + Math.sin(this.time * 4) * 0.6 : 1.8);
    } else {
      this.file.place(this.file.group.position, 0, 0);
    }
    this.world.update(this.time, gate);

    // camera: a slow drift, pointer parallax, and a gentle lean toward the role at work
    const focus = state?.focus ? ROLE[state.focus] : null;
    const lean = this.reduced ? 0 : 0.12;
    const tx = (focus ? focus.x * lean : 0) + this.pointer.x * 0.6;
    const tz = -0.2 + (focus ? (focus.z + 0.2) * lean : 0) - this.pointer.y * 0.4;
    this.target.set(approach(this.target.x, tx, 1.2, dt), 0.4, approach(this.target.z, tz, 1.2, dt));
    this.look.copy(this.target);
    const sway = this.reduced ? 0 : Math.sin(this.time * 0.13) * 0.035;
    const dir = VIEW.clone().applyAxisAngle(new Vector3(0, 1, 0), sway + this.pointer.x * 0.03);
    this.camera.position.copy(this.look).addScaledVector(dir, this.distance);
    this.camera.lookAt(this.look);
    this.camera.updateMatrixWorld();

    this.renderer.info.reset();
    this.post.render(this.renderer, this.scene, this.camera, 0, this.time);
    this.stats.fps = this.adaptive.fps;
    this.stats.calls = this.renderer.info.render.calls;
    this.stats.triangles = this.renderer.info.render.triangles;

    this.pin();
  }

  /** Keeps the bubbles, plates and the file's label over their anchors. */
  private pin(): void {
    const v = new Vector3();
    const place = (key: string, p: Vector3) => {
      const el = this.opts.anchors.get(key);
      if (!el) return;
      v.copy(p).project(this.camera);
      const x = (v.x * 0.5 + 0.5) * this.width;
      const y = (-v.y * 0.5 + 0.5) * this.height;
      placePin(el, x, y, v.z < 1);
    };
    for (const r of ROLES) {
      place(`bubble:${r.id}`, new Vector3(r.x, r.size + 0.3, r.z - 0.2));
    }
    place("gate", new Vector3(APPROVAL_POST[0] + 0.5, 2.3, APPROVAL_POST[1]));
    if (this.file.group.visible) place("file", this.file.group.position.clone().add(new Vector3(-0.25, 0.3, 0.2)));
    const fileEl = this.opts.anchors.get("file");
    if (fileEl) fileEl.style.opacity = this.file.group.visible ? "1" : "0";
  }
}
