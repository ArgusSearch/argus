// The imperative side of the village. It owns the renderer, the camera and the render loop; the page hands it
// the player (the clock and its timeline) and the folded village state, and DOM elements to keep pinned to
// the igloos (bubbles, name plates) and to the case file. React never re-renders per frame: the engine moves
// those elements itself.

import {
  AdditiveBlending,
  CatmullRomCurve3,
  Color,
  DirectionalLight,
  Fog,
  HemisphereLight,
  PCFShadowMap,
  PerspectiveCamera,
  PMREMGenerator,
  Raycaster,
  Scene,
  Sprite,
  SpriteMaterial,
  Vector2,
  Vector3,
  WebGLRenderer,
  type Texture,
} from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { Post } from "../../fx/scene/post";
import { AdaptiveQuality, pixelRatio, TIERS, type QualityMode, type TierSpec } from "../../fx/scene/quality";
import { IDLE_AVATAR, type AvatarCues } from "../avatars/state";
import { measureKeepout, placePin, type Keepout } from "../Overlay";
import type { Player } from "../player";
import { APPROVAL_POST, ROLE, ROLES, ROLE_IDS, type RoleId } from "../roles";
import { growthAt, slotAt, TRAVEL, type VillageState } from "../timeline";
import type { Beat } from "../beats";
import { Bot, BOT_SIZE, CaseFile } from "./bots";
import { Ripples, Sparks } from "./fx";
import { glowTexture } from "./util";
import { Igloos } from "./igloo";
import { buildRoom, SEAT, type Room, type RoomTelemetry } from "./rooms";
import { approach, clamp01, easeInOut } from "./util";
import { doorPoint, route, seatPoint, World } from "./world";

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
/** seconds the camera takes to fly in when the village opens */
const INTRO = 3.2;
/** the approval post, on the snow */
const POST = new Vector3(APPROVAL_POST[0], 0, APPROVAL_POST[1]);

/** A bot on the way: where it is, the step it is on, which way it leans and how much of the gait shows. */
interface Walk {
  pos: Vector3;
  carrying: boolean;
  /** radians; one bounce per half turn */
  phase: number;
  /** -1..1, toward the viewer's left or right */
  lean: number;
  /** -1..1, away from the viewer (up the screen) or toward it */
  away: number;
  /** 0..1: the gait eases in as it sets off and out as it arrives */
  gait: number;
}

function walkAlong(curve: CatmullRomCurve3, local: number, carrying: boolean): Walk {
  const u = easeInOut(local / TRAVEL);
  const tangent = curve.getTangentAt(clamp01(u));
  return {
    pos: curve.getPointAt(clamp01(u)),
    carrying,
    phase: local * 9.5,
    lean: Math.max(-1, Math.min(1, tangent.x * 1.2)),
    away: Math.max(-1, Math.min(1, -tangent.z)),
    gait: clamp01(Math.min(local / 0.3, (TRAVEL - local) / 0.3)),
  };
}

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
  private avatars: AvatarCues = {};
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
  /** frame-stepped by step(): no loop, no adaptive quality */
  private capturing = false;
  private readonly sparks = new Sparks();
  private readonly ripples = new Ripples();
  /** the player time last frame: effects fire only when the clock plays forward */
  private prevT = 0;
  private seekVersion = 0;
  /** 0..1, the camera's fly-in */
  private intro = 0;
  /** 0..1, how far the camera leans in toward a waiting approval */
  private gatePull = 0;
  /** seconds to the approval post's next ring */
  private postCall = 0;
  /** where the case file's light trail left its last spark */
  private trailFrom: Vector3 | null = null;
  /** the metric being placed, as a light rising over the Cartographer's map table */
  private readonly holo = new Sprite(new SpriteMaterial({ map: glowTexture(), transparent: true, depthWrite: false, blending: AdditiveBlending, toneMapped: false, opacity: 0 }));
  /** where the new node sits on the map table, in the scene */
  private readonly holoAt = new Vector3();
  /** the title block the bubbles keep clear of, re-measured about once a second */
  private keepout: Keepout | null = null;
  private keepoutAge = 1;
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
    // The terrain and room furniture stay put. Reuse their shadow map while the camera and bots move.
    this.renderer.shadowMap.autoUpdate = false;
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
    const dpr = window.devicePixelRatio || 1;
    ROLE_IDS.forEach((id, i) => {
      const bot = new Bot(id, 0.13 + i * 0.137, dpr, this.reduced);
      bot.sprite.position.copy(seatPoint(id));
      this.bots.set(id, bot);
      this.scene.add(bot.sprite);
    });
    this.scene.add(this.file.group, this.sparks.group, this.ripples.group);
    this.holo.visible = false;
    this.holo.renderOrder = 5;
    this.scene.add(this.holo);
    // the new node's spot on the map (its canvas at u 0.93, v 0.42), carried into the scene by the room
    const carto = this.rooms.get("cartographer");
    if (carto) {
      this.scene.updateMatrixWorld(true);
      carto.group.localToWorld(this.holoAt.set((0.93 - 0.5) * 1.7, 0.66, SEAT.desk.z + 0.12 - (0.5 - 0.42) * 0.8));
    }

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
  }

  setAvatars(avatars: AvatarCues): void {
    this.avatars = avatars;
  }

  setTelemetry(telemetry: RoomTelemetry): void {
    this.rooms.get("watcher")?.setTelemetry(telemetry);
    this.rooms.get("market")?.setTelemetry(telemetry);
  }

  start(): void {
    if (this.frame || this.disposed || this.capturing) return;
    this.last = performance.now();
    this.adaptive.reset();
    const loop = (now: number) => {
      this.frame = requestAnimationFrame(loop);
      const elapsed = Math.max(0, (now - this.last) / 1000);
      this.last = now;
      try {
        this.render(Math.min(0.1, elapsed), elapsed);
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

  /**
   * Frame-steps the village for captures (window.__village.step(1 / 30)): stops the engine's and the player's
   * own loops, advances both by `dt` seconds and renders one frame, so a recording is smooth however slow the
   * machine is. `release()` hands the clocks back to the browser.
   */
  step(dt: number): void {
    this.stop();
    this.opts.player.stop();
    this.capturing = true;
    this.opts.player.advance(dt);
    this.render(dt);
  }

  release(): void {
    this.capturing = false;
    this.opts.player.start();
    this.start();
  }

  dispose(): void {
    this.disposed = true;
    this.stop();
    this.observer.disconnect();
    for (const c of this.cleanups) c();
    for (const r of this.rooms.values()) r.dispose();
    for (const b of this.bots.values()) b.dispose();
    this.file.dispose();
    this.sparks.dispose();
    this.holo.material.dispose();
    this.ripples.dispose();
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
    const lowShadows = this.tier === TIERS.low || (rung && rung.multiplier < 0.9);
    const fidelity = lowShadows ? TIERS.low : this.tier;
    this.post.setSamples(fidelity.samples);
    this.sun.castShadow = !lowShadows;
    this.renderer.shadowMap.needsUpdate = this.sun.castShadow;
    this.world.setSnow(this.reduced ? 0 : Math.round(fidelity.snow[0] * 1.2));
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
    this.keepoutAge = 1;
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

  private render(dt: number, elapsed = dt): void {
    if (this.sizeDirty) this.resize();
    if (!this.capturing && this.adaptive.sample(elapsed) && this.opts.quality === "auto") this.applyTier();
    this.time += this.reduced ? 0 : dt;
    const player = this.opts.player;
    const tl = player.timeline;
    const t = player.time;
    const state = this.state;

    // the clock moved forward by playing (effects fire), or jumped (a seek, a restart: they do not)
    const jumped = player.seekVersion !== this.seekVersion || t < this.prevT;
    if (jumped) {
      this.trailFrom = null;
      this.sparks.clear();
      this.ripples.clear();
      this.seekVersion = player.seekVersion;
    }
    const flowing = !jumped && t > this.prevT && t - this.prevT < 0.75;
    const prevT = this.prevT;
    this.prevT = t;
    const motion = !this.reduced;

    // who walks where, carrying what
    const index = slotAt(tl, t);
    const walking = new Map<RoleId, Walk>();
    for (let i = Math.max(0, index - 4); motion && i <= index; i++) {
      const slot = tl.slots[i];
      if (!slot?.from) continue;
      const local = t - slot.start;
      const from = slot.from;
      const to = slot.beat.role;
      if (local < TRAVEL) walking.set(from, walkAlong(route(from, to), local, true));
      else if (local < 2 * TRAVEL && !walking.has(from)) walking.set(from, walkAlong(route(to, from), local - TRAVEL, false));
      // the hand-over: the case lands with a ring of light, the room flashes and its bot hops to greet it
      if (flowing && prevT - slot.start < TRAVEL && local >= TRAVEL) this.arrive(slot.from, to);
    }
    if (index !== this.lastIndex) {
      // a beat that just ended: verdicts land, actions are verified
      if (flowing && index === this.lastIndex + 1) this.ended(tl.slots[this.lastIndex]?.beat ?? null);
      if (flowing && index === this.lastIndex + 1) this.began(tl.slots[index]?.beat ?? null);
      this.lastIndex = index;
    } else if (flowing && prevT < tl.total && t === tl.total && !tl.waiting) {
      this.ended(tl.slots[index]?.beat ?? null);
    }

    // where every bot looks: at the case on the move, else at the approval post or the role at work
    const gate = Boolean(state?.gate);
    const carrier = [...walking.entries()].find(([, w]) => w.carrying);
    const focusId = state?.focus ?? null;
    const watched = carrier ? carrier[1].pos : gate ? POST : focusId ? seatPoint(focusId) : null;

    // bots: at their seat unless walking; busy ones paint every frame
    const levels = new Map<string, number>();
    for (const [id, bot] of this.bots) {
      const walk = walking.get(id);
      const home = seatPoint(id);
      const cue = this.avatars[id] ?? IDLE_AVATAR;
      if (walk) {
        bot.sprite.position.copy(walk.pos);
        // calm in the canvas, the gait does the moving: a bounce per step, a lean and a look where it goes
        bot.setCue(IDLE_AVATAR);
        bot.sprite.position.y += motion ? bot.stride(walk.phase, walk.lean, walk.gait) : 0;
        bot.look(walk.lean * 1.5, walk.away * 0.5, 0.95);
      } else {
        bot.sprite.position.lerp(home, 1 - Math.exp(-10 * dt));
        bot.stride(0, 0, 0);
        bot.setCue(cue);
        if (motion && cue.status === "idle") bot.breathe(this.time);
        // the others turn their heads to follow what happens; the one at work keeps its eyes on its desk
        if (watched && id !== focusId && cue.status !== "working" && motion) {
          const dx = watched.x - home.x;
          const dz = watched.z - home.z;
          bot.look(Math.max(-1.4, Math.min(1.4, dx / 5)), Math.max(-0.5, Math.min(0.6, -dz / 9)), 0.6);
        } else bot.look(0, 0, 0);
      }
      bot.update(dt, Boolean(walk));
      levels.set(id, cue.status === "working" ? 1 : cue.status === "waiting" ? 0.85 : 0.3);
    }
    this.igloos.update(dt, levels, this.time);
    const growth = growthAt(tl, index, t);
    this.rooms.get("cartographer")?.grow(growth && !motion ? { ...growth, age: 2.6 } : growth);
    this.showHolo(growth);
    for (const [id, room] of this.rooms) room.tick(this.time, this.avatars[id]?.status === "working");

    // the case file
    const slot = tl.slots[index];
    if (carrier) {
      const p = carrier[1].pos.clone().add(new Vector3(0.32, BOT_SIZE * 0.42, 0.3));
      p.y += motion ? Math.abs(Math.sin(carrier[1].phase)) * 0.12 : 0;
      this.file.place(p, 0.25 + Math.sin(carrier[1].phase) * 0.12, 1);
      this.file.setColor("#7cc4ff", 2);
      if (motion) this.trail(p, "#8fd0ff");
    } else if (state?.beat?.caseId && !(state.beat.kind === "lifecycle" && state.beat.done.endsWith("closed"))) {
      const id = state.beat.role;
      const r = ROLE[id];
      const desk = new Vector3(r.x - 0.62, SEAT.deskTop + 0.12 + Math.sin(this.time * 2) * 0.035, r.z + SEAT.desk.z - 0.05);
      if (gate) desk.set(POST.x, 1.3 + Math.sin(this.time * 2) * 0.05, POST.z);
      // it pops as it lands, then floats over the desk turning slowly
      const since = slot?.from ? t - slot.start - TRAVEL : Infinity;
      const pop = motion && since >= 0 && since < 0.5 ? Math.sin((since / 0.5) * Math.PI) * (1 - since / 0.5) * 0.9 : 0;
      this.file.place(desk, 0, 1, 1 + pop, motion ? Math.sin(this.time * 0.7) * 0.35 : 0);
      this.file.setColor(gate ? "#ff8a6a" : state.beat.outcome === "alarm" ? "#ff7a6a" : "#7cc4ff", gate ? 2.2 + Math.sin(this.time * 4) * 0.6 : 1.8);
      this.trailFrom = null;
    } else {
      this.file.place(this.file.group.position, 0, 0);
      this.trailFrom = null;
    }
    this.world.update(this.time, gate);
    // the approval post calls: a slow ring of coral light on the snow, again and again
    if (gate && motion) {
      this.postCall -= dt;
      if (this.postCall <= 0) {
        this.ripples.emit(POST, "#ff8a6a", 0.5, 3.4, 1.7, 0.9);
        this.postCall = 1.6;
      }
    } else this.postCall = 0;
    this.sparks.update(dt);
    this.ripples.update(dt);

    // camera: flies in once, then a slow drift, pointer parallax and a lean toward the role at work, closer
    // still while a case waits at the approval post
    this.intro = this.reduced ? 1 : Math.min(1, this.intro + dt / INTRO);
    const fly = 1 - Math.pow(1 - this.intro, 3);
    this.gatePull = approach(this.gatePull, gate && motion ? 1 : 0, 1.6, dt);
    const focus = focusId ? ROLE[focusId] : null;
    const lean = this.reduced ? 0 : 0.12 + 0.14 * this.gatePull;
    const toward = gate ? { x: (ROLE.operator.x + POST.x) / 2, z: (ROLE.operator.z + POST.z) / 2 } : focus;
    const px = motion ? this.pointer.x : 0;
    const py = motion ? this.pointer.y : 0;
    const tx = (toward ? toward.x * lean : 0) + px * 0.6;
    const tz = -0.2 + (toward ? (toward.z + 0.2) * lean : 0) - py * 0.4;
    this.target.set(approach(this.target.x, tx, 1.2, dt), 0.4, approach(this.target.z, tz, 1.2, dt));
    this.look.copy(this.target);
    const sway = this.reduced ? 0 : Math.sin(this.time * 0.13) * 0.035;
    const dir = VIEW.clone()
      .setY(VIEW.y + 0.55 * (1 - fly))
      .normalize()
      .applyAxisAngle(new Vector3(0, 1, 0), sway + px * 0.03 - 0.42 * (1 - fly));
    this.camera.position.copy(this.look).addScaledVector(dir, this.distance * (1 + 0.42 * (1 - fly) - 0.07 * this.gatePull));
    this.camera.lookAt(this.look);
    this.camera.updateMatrixWorld();

    this.renderer.info.reset();
    this.post.render(this.renderer, this.scene, this.camera, 0, this.time);
    this.stats.fps = this.adaptive.fps;
    this.stats.calls = this.renderer.info.render.calls;
    this.stats.triangles = this.renderer.info.render.triangles;

    this.pin(dt);
  }

  /** A case reaches the next igloo: a ring of light where it lands, the room flashes, its bot hops to greet it. */
  private arrive(from: RoleId, to: RoleId): void {
    const ig = this.igloos.items.find((it) => it.role.id === to);
    if (ig) ig.flash = 1;
    if (this.reduced) return;
    this.ripples.emit(route(from, to).getPointAt(1), ROLE[to].color, 0.3, 2.2, 0.9, 0.85);
    this.bots.get(to)?.poke();
  }

  /**
   * The metric being placed rises off the map table as a light, in the verdict's color, swells as it lands in
   * the map and fades back into the table.
   */
  private showHolo(g: ReturnType<typeof growthAt>): void {
    const on = g && !this.reduced && g.age < 2.6;
    this.holo.visible = Boolean(on);
    if (!g || !on) return;
    const rise = 1 - Math.pow(1 - clamp01(g.age / 0.9), 3);
    const land = clamp01((g.age - 0.6) / 0.5);
    const fade = 1 - clamp01((g.age - 1.8) / 0.8);
    const hex = g.kind === "placed" ? "#5fe0a2" : g.kind === "held" ? "#ffc56a" : "#ff7a6a";
    this.holo.material.color.set(hex).multiplyScalar(2.4);
    this.holo.position.copy(this.holoAt).setY(this.holoAt.y + 0.1 + rise * 0.55 - land * 0.25);
    this.holo.scale.setScalar((0.35 + rise * 0.35 + Math.sin(land * Math.PI) * 0.35) * (g.kind === "rejected" ? 1 - land * 0.4 : 1));
    this.holo.material.opacity = Math.min(1, g.age / 0.2) * fade;
  }

  /** A beat starts: an alarm rings out from the watcher's door. */
  private began(beat: Beat | null): void {
    if (!beat || this.reduced) return;
    if (beat.kind === "detect" || (beat.role === "watcher" && beat.outcome === "alarm")) {
      const ig = this.igloos.items.find((it) => it.role.id === beat.role);
      if (ig) ig.flash = 1;
      this.ripples.emit(doorPoint(beat.role), "#ff7a6a", 0.4, 3.2, 1.3, 0.9);
    }
  }

  /** A beat ends: a verdict that holds or an action that is verified throws light; a rejection rings red. */
  private ended(beat: Beat | null): void {
    if (!beat || this.reduced) return;
    const r = ROLE[beat.role];
    const over = new Vector3(r.x, 1.25, r.z + 0.2);
    const win = (beat.kind === "verdict" || beat.kind === "decision" || beat.kind === "effect") && beat.outcome === "ok";
    if (win) {
      this.sparks.burst(over, [r.color, "#ffd98a", "#ffffff"], beat.kind === "effect" ? 40 : 28, beat.kind === "effect" ? 1.15 : 1);
      this.ripples.emit(doorPoint(beat.role), "#7be3b0", 0.4, 2.8, 1.1, 0.8);
      const ig = this.igloos.items.find((it) => it.role.id === beat.role);
      if (ig) ig.flash = 0.8;
    } else if (beat.kind === "verdict" || beat.kind === "decision") {
      this.ripples.emit(doorPoint(beat.role), beat.outcome === "alarm" || beat.outcome === "denied" || beat.outcome === "refuted" ? "#ff7a6a" : "#ffc56a", 0.4, 2.6, 1.1, 0.75);
    }
  }

  /** The case file leaves a trail of light: sparks every 0.11 units of the way, so it looks the same at any frame rate. */
  private trail(p: Vector3, hex: string): void {
    if (!this.trailFrom || this.trailFrom.distanceTo(p) > 2) {
      this.trailFrom = p.clone();
      return;
    }
    const step = 0.11;
    let d = this.trailFrom.distanceTo(p);
    while (d >= step) {
      this.trailFrom.lerp(p, step / d);
      d -= step;
      const drift = new Vector3((Math.sin(this.trailFrom.x * 13.1) * 0.5) * 0.25, 0.25 + Math.abs(Math.sin(this.trailFrom.z * 7.3)) * 0.2, 0);
      this.sparks.emit(this.trailFrom, drift, 0.7, 0.24, hex, 1.7, -0.15, 1.4);
    }
  }

  /** Keeps the bubbles, plates and the file's label over their anchors. */
  private pin(dt: number): void {
    this.keepoutAge += dt;
    if (this.keepoutAge > 1) {
      this.keepout = measureKeepout(this.opts.mount);
      this.keepoutAge = 0;
    }
    const v = new Vector3();
    const place = (key: string, p: Vector3) => {
      const el = this.opts.anchors.get(key);
      if (!el) return;
      v.copy(p).project(this.camera);
      const x = (v.x * 0.5 + 0.5) * this.width;
      const y = (-v.y * 0.5 + 0.5) * this.height;
      placePin(el, x, y, v.z < 1, this.keepout);
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
