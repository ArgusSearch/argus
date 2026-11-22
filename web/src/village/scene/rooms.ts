// The rooms inside the igloos: low-poly furniture for each job, in the igloo's own frame (floor at y = 0, the
// opening toward +z, the back wall at z ~ -1.9). The bot sits behind its desk, facing the camera.
// Screens, the stock board and the map are canvas textures; the live ones redraw a few times a second.

import {
  BoxGeometry,
  CanvasTexture,
  Color,
  ConeGeometry,
  CylinderGeometry,
  Group,
  Line,
  BufferGeometry,
  LineBasicMaterial,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  PlaneGeometry,
  SphereGeometry,
  SRGBColorSpace,
  TorusGeometry,
  Vector3,
  type Material,
  type Object3D,
} from "three";
import { mergeGeometries } from "three/addons/utils/BufferGeometryUtils.js";
import type { Growth } from "../timeline";
import type { RoleId } from "../roles";
import type { MarketVerdict, WatchSeries } from "../telemetry";
import { seeded } from "./util";

/** Where things sit in every room. */
export const SEAT = { bot: new Vector3(0, 0, -0.15), desk: new Vector3(0, 0, 0.62), deskTop: 0.62 };

interface Kit {
  mat: (color: string, rough?: number, metal?: number) => MeshStandardMaterial;
  glow: (color: string, intensity?: number) => MeshBasicMaterial;
  box: (w: number, h: number, d: number, m: Material, x: number, y: number, z: number) => Mesh;
  cyl: (rt: number, rb: number, h: number, m: Material, x: number, y: number, z: number, seg?: number) => Mesh;
  screen: (draw: (ctx: CanvasRenderingContext2D, w: number, h: number, t: number) => void, w: number, h: number, px?: number, animated?: boolean) => { mesh: Mesh; tick: (t: number) => void };
}

export interface Room {
  group: Group;
  /** redraws live textures; called a few times a second */
  tick: (t: number, busy: boolean) => void;
  /** the Cartographer's latest placement, drawn growing into its map; other rooms ignore it */
  grow: (g: Growth | null) => void;
  setTelemetry: (data: RoomTelemetry) => void;
  dispose: () => void;
}

export interface RoomTelemetry {
  watch: readonly WatchSeries[];
  market: MarketVerdict | null;
}

function kit(disposables: { dispose(): void }[], ticks: ((t: number) => void)[]): Kit {
  const geos = new Map<string, BufferGeometry>();
  const geo = <T extends BufferGeometry>(key: string, make: () => T) => {
    let g = geos.get(key);
    if (!g) {
      g = make();
      geos.set(key, g);
      disposables.push(g);
    }
    return g as T;
  };
  const mats = new Map<string, Material>();
  const mat = (color: string, rough = 0.75, metal = 0) => {
    const key = `s:${color}:${rough}:${metal}`;
    let m = mats.get(key) as MeshStandardMaterial | undefined;
    if (!m) {
      m = new MeshStandardMaterial({ color, roughness: rough, metalness: metal, flatShading: true });
      mats.set(key, m);
      disposables.push(m);
    }
    return m;
  };
  const glow = (color: string, intensity = 1.6) => {
    const key = `g:${color}:${intensity}`;
    let m = mats.get(key) as MeshBasicMaterial | undefined;
    if (!m) {
      m = new MeshBasicMaterial({ color: new Color(color).multiplyScalar(intensity), toneMapped: false });
      mats.set(key, m);
      disposables.push(m);
    }
    return m;
  };
  const box = (w: number, h: number, d: number, m: Material, x: number, y: number, z: number) => {
    const mesh = new Mesh(
      geo(`b:${w}:${h}:${d}`, () => new BoxGeometry(w, h, d)),
      m,
    );
    mesh.position.set(x, y, z);
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    return mesh;
  };
  const cyl = (rt: number, rb: number, h: number, m: Material, x: number, y: number, z: number, seg = 10) => {
    const mesh = new Mesh(
      geo(`c:${rt}:${rb}:${h}:${seg}`, () => new CylinderGeometry(rt, rb, h, seg)),
      m,
    );
    mesh.position.set(x, y, z);
    mesh.castShadow = true;
    return mesh;
  };
  const screen: Kit["screen"] = (draw, w, h, px = 256, animated = true) => {
    const canvas = document.createElement("canvas");
    canvas.width = px;
    canvas.height = Math.round((px * h) / w);
    const ctx = canvas.getContext("2d") as CanvasRenderingContext2D;
    const texture = new CanvasTexture(canvas);
    texture.colorSpace = SRGBColorSpace;
    const material = new MeshBasicMaterial({ map: texture, toneMapped: false });
    material.color.setScalar(1.6);
    const mesh = new Mesh(new PlaneGeometry(w, h), material);
    disposables.push(texture, material, mesh.geometry);
    const tick = (t: number) => {
      draw(ctx, canvas.width, canvas.height, t);
      texture.needsUpdate = true;
    };
    tick(0);
    if (animated) ticks.push(tick);
    return { mesh, tick };
  };
  return { mat, glow, box, cyl, screen };
}

/** Bake stationary furniture into room-space batches, keeping its original material and shadow settings. */
function batchFurniture(root: Group, moving: Set<Object3D>, disposables: { dispose(): void }[]): void {
  const batches = new Map<string, Mesh[]>();
  function collect(object: Object3D): void {
    if (moving.has(object)) return;
    if (object instanceof Mesh && object.material instanceof MeshStandardMaterial && (object.geometry instanceof BoxGeometry || object.geometry instanceof CylinderGeometry)) {
      const key = `${object.material.id}:${object.castShadow}:${object.receiveShadow}`;
      const batch = batches.get(key) ?? [];
      batch.push(object);
      batches.set(key, batch);
    }
    for (const child of object.children) collect(child);
  }
  collect(root);
  root.updateMatrixWorld(true);
  for (const meshes of batches.values()) {
    if (meshes.length < 2) continue;
    const copies = meshes.map((mesh) => mesh.geometry.clone().applyMatrix4(mesh.matrixWorld));
    const geometry = mergeGeometries(copies);
    for (const copy of copies) copy.dispose();
    if (!geometry) continue;
    const batch = new Mesh(geometry, meshes[0].material);
    batch.castShadow = meshes[0].castShadow;
    batch.receiveShadow = meshes[0].receiveShadow;
    for (const mesh of meshes) mesh.removeFromParent();
    root.add(batch);
    disposables.push(geometry);
  }
}

// ---------------------------------------------------------------- shared pieces

const WOOD = "#9a6b45";
const WOOD_LIGHT = "#c08f62";
const METAL = "#c9d2de";
const PAPER = "#f6f1e7";

function desk(k: Kit, g: Group, width = 1.7) {
  const top = k.mat(WOOD_LIGHT, 0.7);
  const leg = k.mat(WOOD, 0.8);
  const y = SEAT.deskTop;
  g.add(k.box(width, 0.07, 0.62, top, 0, y, SEAT.desk.z));
  // a front panel, so the desk reads as a solid piece of furniture from the camera
  g.add(k.box(width - 0.06, y - 0.05, 0.05, leg, 0, (y - 0.05) / 2, SEAT.desk.z + 0.28));
  for (const s of [-1, 1]) g.add(k.box(0.06, y, 0.56, leg, s * (width / 2 - 0.05), y / 2, SEAT.desk.z));
}

function shelf(k: Kit, g: Group, x: number, z: number, rot: number, seed: number) {
  const rand = seeded(seed);
  const s = new Group();
  const wood = k.mat(WOOD, 0.85);
  s.add(k.box(0.75, 1.25, 0.28, wood, 0, 0.625, 0));
  const colors = ["#b64e3c", "#3f6aa8", "#d39a3a", "#4b8a5d", "#7d5aa6", "#e1d2b0"];
  for (let row = 0; row < 3; row++) {
    let x0 = -0.31;
    while (x0 < 0.28) {
      const w = 0.05 + rand() * 0.05;
      const h = 0.2 + rand() * 0.1;
      s.add(k.box(w, h, 0.2, k.mat(colors[Math.floor(rand() * colors.length)], 0.8), x0 + w / 2, 0.12 + row * 0.38 + h / 2, 0.04));
      x0 += w + 0.012;
    }
  }
  s.position.set(x, 0, z);
  s.rotation.y = rot;
  g.add(s);
}

function lamp(k: Kit, g: Group, x: number, z: number) {
  const metal = k.mat("#3b3f46", 0.5, 0.4);
  g.add(k.cyl(0.08, 0.1, 0.04, metal, x, SEAT.deskTop + 0.05, z));
  const arm = k.cyl(0.015, 0.015, 0.38, metal, x, SEAT.deskTop + 0.24, z);
  g.add(arm);
  const shade = new Mesh(new ConeGeometry(0.11, 0.14, 12, 1, true), k.mat("#2f3338", 0.5, 0.3));
  shade.position.set(x + 0.06, SEAT.deskTop + 0.44, z);
  shade.rotation.z = 0.6;
  g.add(shade);
  const bulb = new Mesh(new SphereGeometry(0.045, 10, 8), k.glow("#ffd49a", 3));
  bulb.position.set(x + 0.08, SEAT.deskTop + 0.4, z);
  g.add(bulb);
}

function mug(k: Kit, g: Group, x: number, z: number, color = "#f2efe8") {
  g.add(k.cyl(0.045, 0.04, 0.09, k.mat(color, 0.4), x, SEAT.deskTop + 0.08, z, 10));
}

function papers(k: Kit, g: Group, x: number, z: number, n: number, seed: number) {
  const rand = seeded(seed);
  const paper = k.mat(PAPER, 0.95);
  for (let i = 0; i < n; i++) {
    const p = k.box(0.24, 0.012, 0.32, paper, x + (rand() - 0.5) * 0.03, SEAT.deskTop + 0.04 + i * 0.013, z + (rand() - 0.5) * 0.03);
    p.rotation.y = (rand() - 0.5) * 0.2;
    g.add(p);
  }
}

function plant(k: Kit, g: Group, x: number, z: number, y = 0) {
  g.add(k.cyl(0.11, 0.08, 0.18, k.mat("#c86f4a", 0.8), x, y + 0.09, z, 8));
  const leaves = k.mat("#4f8f55", 0.8);
  for (let i = 0; i < 5; i++) {
    const leaf = new Mesh(new ConeGeometry(0.05, 0.32, 5), leaves);
    leaf.position.set(x + Math.cos(i * 1.3) * 0.05, y + 0.32, z + Math.sin(i * 1.3) * 0.05);
    leaf.rotation.set(Math.sin(i * 1.3) * 0.5, 0, -Math.cos(i * 1.3) * 0.5);
    g.add(leaf);
  }
}

/** Something on the back wall, tilted to follow the dome. */
function onWall(mesh: Mesh | Group, angle: number, y: number, r = 1.62) {
  mesh.position.set(Math.sin(angle) * r, y, -Math.cos(angle) * r);
  mesh.rotation.y = -angle;
  return mesh;
}

// ---------------------------------------------------------------- canvas pictures

function chart(ctx: CanvasRenderingContext2D, w: number, h: number, series: WatchSeries | undefined, color: string) {
  ctx.fillStyle = "#16304f";
  ctx.fillRect(0, 0, w, h);
  if (!series) return;
  ctx.fillStyle = color;
  ctx.strokeStyle = color;
  ctx.font = "600 13px sans-serif";
  ctx.fillText(series.label, 8, 16, w - 16);
  ctx.lineWidth = Math.max(2, w / 70);
  const max = Math.max(1, ...series.values.map((value) => value ?? 0));
  const dx = (w - 16) / Math.max(1, series.values.length - 1);
  let connected = false;
  ctx.beginPath();
  series.values.forEach((value, i) => {
    if (value === null) {
      connected = false;
      return;
    }
    const x = i * dx + 8;
    const y = h - 6 - (value / max) * (h - 29);
    if (connected) ctx.lineTo(x, y);
    else {
      ctx.fillRect(x - 1, y - 1, 2, 2);
      ctx.moveTo(x, y);
    }
    connected = true;
  });
  ctx.stroke();
}

const MARKET_LABEL: Record<MarketVerdict, { text: string; color: string }> = {
  market: { text: "Market-wide move", color: "#8ef0c4" },
  us: { text: "Shop-specific move", color: "#ff9f8b" },
  inconclusive: { text: "Inconclusive", color: "#ffd18a" },
};

function stockBoard(ctx: CanvasRenderingContext2D, w: number, h: number, verdict: MarketVerdict | null) {
  ctx.fillStyle = "#0b1520";
  ctx.fillRect(0, 0, w, h);
  ctx.textAlign = "center";
  ctx.fillStyle = "#b0c9dc";
  ctx.font = "600 20px sans-serif";
  ctx.fillText("MARKET COMPARISON", w / 2, h * 0.38, w - 24);
  if (!verdict) return;
  ctx.fillStyle = MARKET_LABEL[verdict].color;
  ctx.font = "600 30px sans-serif";
  ctx.fillText(MARKET_LABEL[verdict].text, w / 2, h * 0.68, w - 24);
}

function mapPicture(ctx: CanvasRenderingContext2D, w: number, h: number, t: number, growth: Growth | null = null) {
  ctx.fillStyle = "#e9dcbc";
  ctx.fillRect(0, 0, w, h);
  ctx.strokeStyle = "rgba(120,90,50,0.35)";
  ctx.lineWidth = 2;
  for (let i = 0; i < 6; i++) {
    ctx.beginPath();
    ctx.ellipse(w * (0.2 + 0.12 * i), h * (0.3 + 0.08 * (i % 3)), w * 0.12, h * 0.08, 0.4, 0, Math.PI * 2);
    ctx.stroke();
  }
  const nodes: [number, number][] = [
    [0.15, 0.3],
    [0.35, 0.18],
    [0.55, 0.35],
    [0.75, 0.22],
    [0.3, 0.65],
    [0.55, 0.72],
    [0.82, 0.62],
  ];
  const edges = [
    [0, 1],
    [1, 2],
    [2, 3],
    [0, 4],
    [4, 5],
    [2, 5],
    [5, 6],
    [3, 6],
  ];
  const lit = Math.floor(t * 1.2) % edges.length;
  edges.forEach(([a, b], i) => {
    ctx.strokeStyle = i === lit ? "#ffffff" : "#6a7fd8";
    ctx.lineWidth = i === lit ? 6 : 4;
    ctx.beginPath();
    ctx.moveTo(nodes[a][0] * w, nodes[a][1] * h);
    ctx.lineTo(nodes[b][0] * w, nodes[b][1] * h);
    ctx.stroke();
  });
  for (const [x, y] of nodes) {
    ctx.fillStyle = "#a495ff";
    ctx.beginPath();
    ctx.arc(x * w, y * h, 10, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(x * w, y * h, 4, 0, Math.PI * 2);
    ctx.fill();
  }
  if (growth) newNode(ctx, w, h, nodes, growth);
}

const easeOutBack = (x: number) => {
  const c = 1.9;
  const k = Math.min(1, Math.max(0, x));
  return 1 + (c + 1) * Math.pow(k - 1, 3) + c * Math.pow(k - 1, 2);
};

/**
 * The metric being placed grows into the map: its edges draw out from the two nodes it hangs off, the node
 * springs in with a ring of light, and settles green (placed), amber and dashed (held) or red and crossed out,
 * fading away (rejected).
 */
function newNode(ctx: CanvasRenderingContext2D, w: number, h: number, nodes: [number, number][], g: Growth) {
  const at: [number, number] = [0.93 * w, 0.42 * h];
  const tone = g.kind === "placed" ? "#2fb57a" : g.kind === "held" ? "#d99a2b" : "#e0564a";
  const fadeOut = g.kind === "rejected" ? Math.max(0, Math.min(1, (g.age - 1.6) / 0.8)) : 0;
  if (fadeOut >= 1) return;
  ctx.save();
  ctx.globalAlpha = 1 - fadeOut;
  const draw = Math.min(1, g.age / 0.8);
  ctx.strokeStyle = tone;
  ctx.lineWidth = 5;
  ctx.lineCap = "round";
  if (g.kind !== "placed") ctx.setLineDash([10, 9]);
  for (const i of [3, 6]) {
    const [x, y] = [nodes[i][0] * w, nodes[i][1] * h];
    ctx.beginPath();
    ctx.moveTo(x, y);
    ctx.lineTo(x + (at[0] - x) * draw, y + (at[1] - y) * draw);
    ctx.stroke();
  }
  ctx.setLineDash([]);
  const grow = easeOutBack((g.age - 0.45) / 0.55);
  if (grow > 0) {
    // the ring of light as it lands
    const ring = Math.min(1, Math.max(0, (g.age - 0.6) / 0.9));
    if (ring > 0 && ring < 1) {
      ctx.strokeStyle = tone;
      ctx.globalAlpha = (1 - fadeOut) * (1 - ring) * 0.9;
      ctx.lineWidth = 4;
      ctx.beginPath();
      ctx.arc(at[0], at[1], 14 + ring * 34, 0, Math.PI * 2);
      ctx.stroke();
      ctx.globalAlpha = 1 - fadeOut;
    }
    const pulse = g.kind === "held" ? 1 + Math.sin(g.age * 5) * 0.08 : 1;
    const r = 13 * grow * pulse;
    ctx.fillStyle = tone;
    ctx.beginPath();
    ctx.arc(at[0], at[1], r, 0, Math.PI * 2);
    ctx.fill();
    ctx.fillStyle = "#ffffff";
    ctx.beginPath();
    ctx.arc(at[0], at[1], r * 0.42, 0, Math.PI * 2);
    ctx.fill();
    if (g.kind === "rejected" && g.age > 1.05) {
      ctx.strokeStyle = "#ffffff";
      ctx.lineWidth = 4;
      const c = r * 0.45;
      ctx.beginPath();
      ctx.moveTo(at[0] - c, at[1] - c);
      ctx.lineTo(at[0] + c, at[1] + c);
      ctx.moveTo(at[0] + c, at[1] - c);
      ctx.lineTo(at[0] - c, at[1] + c);
      ctx.stroke();
    }
  }
  ctx.restore();
}

// ---------------------------------------------------------------- the seven rooms

export function buildRoom(role: RoleId, color: string): Room {
  const disposables: { dispose(): void }[] = [];
  const ticks: ((t: number) => void)[] = [];
  const k = kit(disposables, ticks);
  const g = new Group();
  const telemetryScreens: ((t: number) => void)[] = [];
  const moving = new Set<Object3D>();
  let telemetry: RoomTelemetry = { watch: [], market: null };
  let tickBusy: ((t: number) => void) | null = null;
  /** the Cartographer's latest placement (only its map reads it) */
  let growth: Growth | null = null;
  let growthChanged = false;

  switch (role) {
    case "watcher": {
      desk(k, g, 1.8);
      const frame = k.mat("#2a3240", 0.4, 0.3);
      for (let i = 0; i < 6; i++) {
        const angle = -0.62 + (i % 3) * 0.62;
        const y = i < 3 ? 1.05 : 1.55;
        const s = k.screen((ctx, w, h) => chart(ctx, w, h, telemetry.watch[i], i % 2 ? "#7cc4ff" : "#9ff0d0"), 0.62, 0.4, 160, false);
        telemetryScreens.push(s.tick);
        const holder = new Group();
        holder.add(k.box(0.68, 0.46, 0.04, frame, 0, 0, -0.025));
        s.mesh.position.z = 0.002;
        holder.add(s.mesh);
        g.add(onWall(holder, angle, y, 1.55 - (i < 3 ? 0 : 0.08)));
      }
      // a small telescope on a tripod by the opening
      const brass = k.mat("#c9a25a", 0.35, 0.6);
      const tube = k.cyl(0.05, 0.07, 0.55, brass, 1.25, 1.05, 0.55);
      tube.rotation.z = 1.1;
      g.add(tube);
      for (let i = 0; i < 3; i++) {
        const legM = k.cyl(0.012, 0.012, 1.0, k.mat("#4a3b2e", 0.8), 1.25 + Math.cos(i * 2.1) * 0.12, 0.48, 0.55 + Math.sin(i * 2.1) * 0.12);
        legM.rotation.set(Math.sin(i * 2.1) * 0.25, 0, -Math.cos(i * 2.1) * 0.25);
        g.add(legM);
      }
      mug(k, g, 0.6, SEAT.desk.z + 0.05);
      const laptop = k.box(0.42, 0.02, 0.3, k.mat("#d6dbe3", 0.35, 0.5), -0.35, SEAT.deskTop + 0.05, SEAT.desk.z);
      g.add(laptop);
      break;
    }
    case "detective": {
      desk(k, g);
      const cork = k.mat("#b47c48", 0.95);
      const board = new Group();
      board.add(k.box(1.55, 0.95, 0.05, cork, 0, 0, 0));
      board.add(k.box(1.62, 1.02, 0.03, k.mat(WOOD, 0.8), 0, 0, -0.03));
      const rand = seeded(5);
      const pins: Vector3[] = [];
      for (let i = 0; i < 7; i++) {
        const x = -0.6 + (i % 4) * 0.4 + (rand() - 0.5) * 0.1;
        const y = 0.22 - Math.floor(i / 4) * 0.42 + (rand() - 0.5) * 0.08;
        const card = k.box(0.22, 0.16, 0.01, k.mat(i % 3 ? PAPER : "#f4e3a1", 0.9), x, y, 0.035);
        card.rotation.z = (rand() - 0.5) * 0.2;
        board.add(card);
        const pin = new Mesh(new SphereGeometry(0.02, 6, 4), k.mat("#d63b35", 0.4));
        pin.position.set(x, y + 0.06, 0.05);
        board.add(pin);
        pins.push(new Vector3(x, y + 0.06, 0.05));
      }
      const string = new Line(
        new BufferGeometry().setFromPoints([pins[0], pins[2], pins[5], pins[1], pins[3], pins[6], pins[4]]),
        new LineBasicMaterial({ color: "#e0332e" }),
      );
      board.add(string);
      disposables.push(string.geometry, string.material as Material);
      g.add(onWall(board, 0, 1.3, 1.56));
      // the magnifier on the desk
      const glass = new Mesh(new TorusGeometry(0.11, 0.018, 8, 20), k.mat("#2b2b2b", 0.4, 0.5));
      glass.rotation.x = -Math.PI / 2 + 0.25;
      glass.position.set(0.45, SEAT.deskTop + 0.06, SEAT.desk.z + 0.05);
      g.add(glass);
      const lens = new Mesh(new SphereGeometry(0.1, 12, 6), new MeshStandardMaterial({ color: "#cfe7ff", roughness: 0.05, transparent: true, opacity: 0.45 }));
      lens.scale.y = 0.15;
      lens.position.copy(glass.position);
      disposables.push(lens.material as Material, lens.geometry);
      g.add(lens);
      const handle = k.cyl(0.02, 0.02, 0.2, k.mat("#3b2a1c", 0.6), 0.6, SEAT.deskTop + 0.05, SEAT.desk.z + 0.18);
      handle.rotation.set(Math.PI / 2, 0, 0.7);
      g.add(handle);
      papers(k, g, -0.45, SEAT.desk.z, 4, 3);
      lamp(k, g, -0.75, SEAT.desk.z - 0.15);
      shelf(k, g, -1.25, -0.6, 0.9, 11);
      break;
    }
    case "skeptic": {
      desk(k, g, 1.6);
      // the lab bench with flasks along the right wall
      g.add(k.box(0.5, 0.75, 1.1, k.mat(WOOD_LIGHT, 0.7), 1.2, 0.375, -0.45));
      const liquids = ["#7cf0c8", "#c38bff", "#7cc4ff"];
      liquids.forEach((c, i) => {
        const z = -0.85 + i * 0.32;
        g.add(k.cyl(0.03, 0.09, 0.2, new MeshStandardMaterial({ color: "#e8f4ff", roughness: 0.05, transparent: true, opacity: 0.5 }), 1.2, 0.86, z));
        g.add(k.cyl(0.075, 0.085, 0.1, k.glow(c, 1.8), 1.2, 0.81, z));
      });
      // the balance on a stand behind the desk
      const gold = k.mat("#d8ad55", 0.3, 0.7);
      const scale = new Group();
      scale.add(k.cyl(0.13, 0.16, 0.05, gold, 0, 0, 0));
      scale.add(k.cyl(0.02, 0.02, 0.6, gold, 0, 0.3, 0));
      const beam = new Group();
      moving.add(beam);
      beam.add(k.box(0.75, 0.025, 0.025, gold, 0, 0, 0));
      for (const s of [-1, 1]) {
        beam.add(k.cyl(0.004, 0.004, 0.22, gold, s * 0.36, -0.11, 0));
        beam.add(k.cyl(0.12, 0.08, 0.03, gold, s * 0.36, -0.23, 0, 14));
      }
      beam.position.y = 0.6;
      scale.add(beam);
      scale.position.set(-0.6, SEAT.deskTop + 0.04, SEAT.desk.z);
      g.add(scale);
      tickBusy = (t) => {
        beam.rotation.z = Math.sin(t * 1.3) * 0.12;
      };
      shelf(k, g, -1.25, -0.55, 0.9, 21);
      plant(k, g, 0.7, SEAT.desk.z, SEAT.deskTop + 0.03);
      break;
    }
    case "market": {
      desk(k, g, 1.7);
      const s = k.screen((ctx, w, h) => stockBoard(ctx, w, h, telemetry.market), 1.5, 0.82, 320, false);
      telemetryScreens.push(s.tick);
      const holder = new Group();
      holder.add(k.box(1.58, 0.9, 0.05, k.mat("#1f2630", 0.4, 0.3), 0, 0, -0.03));
      s.mesh.position.z = 0.002;
      holder.add(s.mesh);
      g.add(onWall(holder, 0, 1.35, 1.5));
      const laptop = k.box(0.42, 0.02, 0.3, k.mat("#d6dbe3", 0.35, 0.5), 0.2, SEAT.deskTop + 0.05, SEAT.desk.z);
      g.add(laptop);
      const lid = k.box(0.42, 0.28, 0.02, k.mat("#d6dbe3", 0.35, 0.5), 0.2, SEAT.deskTop + 0.19, SEAT.desk.z - 0.15);
      lid.rotation.x = -0.25;
      g.add(lid);
      mug(k, g, -0.45, SEAT.desk.z + 0.05, "#e8f6ee");
      plant(k, g, 1.15, 0.1);
      shelf(k, g, -1.25, -0.55, 0.9, 31);
      break;
    }
    case "narrator": {
      desk(k, g, 1.7);
      const paper = k.mat(PAPER, 0.95);
      for (let i = 0; i < 14; i++) {
        const sheet = k.box(0.3, 0.018, 0.38, paper, -0.5 + (i % 3) * 0.004, SEAT.deskTop + 0.05 + i * 0.019, SEAT.desk.z - 0.05);
        sheet.rotation.y = Math.sin(i * 1.7) * 0.06;
        g.add(sheet);
      }
      papers(k, g, 0.15, SEAT.desk.z + 0.02, 2, 8);
      const quill = k.cyl(0.006, 0.012, 0.3, k.mat("#f3f0ea", 0.6), 0.3, SEAT.deskTop + 0.1, SEAT.desk.z + 0.02);
      quill.rotation.z = 1.1;
      g.add(quill);
      lamp(k, g, 0.65, SEAT.desk.z - 0.12);
      mug(k, g, 0.35, SEAT.desk.z + 0.2, "#f6e7c8");
      shelf(k, g, -0.55, -1.35, 0.35, 41);
      shelf(k, g, 0.55, -1.35, -0.35, 42);
      break;
    }
    case "operator": {
      // the control desk: a slanted panel with levers and dials
      const body = k.mat("#7c8794", 0.55, 0.35);
      g.add(k.box(1.8, 0.58, 0.6, body, 0, 0.29, SEAT.desk.z));
      const panel = k.box(1.8, 0.05, 0.42, k.mat("#56606c", 0.5, 0.4), 0, 0.64, SEAT.desk.z - 0.06);
      panel.rotation.x = 0.35;
      g.add(panel);
      const levers: Mesh[] = [];
      for (let i = 0; i < 3; i++) {
        const lever = new Group();
        lever.add(k.cyl(0.015, 0.015, 0.26, k.mat("#d7dde5", 0.3, 0.7), 0, 0.13, 0));
        const knob = new Mesh(new SphereGeometry(0.045, 10, 8), k.mat("#d94a3a", 0.35));
        knob.position.y = 0.27;
        lever.add(knob);
        lever.position.set(-0.55 + i * 0.18, 0.66, SEAT.desk.z + 0.02);
        lever.rotation.x = 0.35;
        g.add(lever);
        levers.push(knob);
      }
      ["#3fdf8f", "#e8b04a", "#ff5c5c", "#36c9b6"].forEach((c, i) => {
        const dot = new Mesh(new SphereGeometry(0.03, 8, 6), k.glow(c, 2.2));
        dot.position.set(0.15 + i * 0.12, 0.69, SEAT.desk.z + 0.08);
        g.add(dot);
      });
      for (let i = 0; i < 2; i++) {
        const dial = new Mesh(new CylinderGeometry(0.09, 0.09, 0.02, 18), k.mat("#f3efe6", 0.5));
        dial.rotation.x = Math.PI / 2 + 0.35;
        dial.position.set(0.45 + i * 0.25, 0.72, SEAT.desk.z - 0.12);
        disposables.push(dial.geometry);
        g.add(dial);
      }
      // the tool wall
      const peg = new Group();
      peg.add(k.box(1.3, 0.8, 0.04, k.mat("#d8c4a2", 0.9), 0, 0, 0));
      for (let i = 0; i < 5; i++) peg.add(k.box(0.05, 0.36 - (i % 2) * 0.1, 0.03, k.mat(METAL, 0.3, 0.8), -0.45 + i * 0.22, 0.05, 0.04));
      g.add(onWall(peg, 0.45, 1.35, 1.52));
      shelf(k, g, -1.25, -0.5, 0.9, 51);
      tickBusy = (t) => {
        levers.forEach((knob, i) => (knob.position.y = 0.27 + Math.max(0, Math.sin(t * 3 + i * 1.4)) * 0.03));
      };
      break;
    }
    case "cartographer": {
      // the map table
      g.add(k.box(1.9, 0.08, 0.95, k.mat(WOOD_LIGHT, 0.7), 0, 0.6, SEAT.desk.z + 0.12));
      for (const sx of [-1, 1]) for (const sz of [-1, 1]) g.add(k.box(0.07, 0.56, 0.07, k.mat(WOOD, 0.8), sx * 0.88, 0.28, SEAT.desk.z + 0.12 + sz * 0.42));
      const map = k.screen((ctx, w, h, t) => mapPicture(ctx, w, h, t, growth), 1.7, 0.8, 340);
      map.mesh.rotation.x = -Math.PI / 2;
      map.mesh.position.set(0, 0.645, SEAT.desk.z + 0.12);
      g.add(map.mesh);
      const gold = k.mat("#d8ad55", 0.3, 0.7);
      g.add(k.cyl(0.11, 0.11, 0.02, gold, 0.65, 0.66, SEAT.desk.z + 0.35, 16));
      const roll = k.cyl(0.05, 0.05, 0.5, k.mat("#e9dcbc", 0.9), -0.75, 0.7, SEAT.desk.z - 0.25);
      roll.rotation.z = Math.PI / 2;
      g.add(roll);
      // a globe on the shelf
      shelf(k, g, 1.2, -0.6, -0.9, 61);
      const globe = new Mesh(new SphereGeometry(0.17, 14, 10), k.mat("#5aa7c8", 0.6));
      globe.position.set(-1.15, 1.45, -0.7);
      disposables.push(globe.geometry);
      g.add(globe);
      g.add(k.cyl(0.08, 0.1, 0.04, gold, -1.15, 1.26, -0.7));
      shelf(k, g, -1.25, -0.65, 0.9, 62);
      break;
    }
  }

  // a warm lantern hanging at the top of every room
  const lantern = new Mesh(new SphereGeometry(0.07, 10, 8), new MeshBasicMaterial({ color: new Color("#ffd08a").multiplyScalar(2.4), toneMapped: false }));
  lantern.position.set(0.0, 1.85, -0.55);
  disposables.push(lantern.geometry, lantern.material as Material);
  g.add(lantern);
  void color;
  batchFurniture(g, moving, disposables);

  let last = -1;
  return {
    group: g,
    tick: (t, busy) => {
      if (busy && tickBusy) tickBusy(t);
      // live textures at about 8 frames a second, every frame while a new node grows into the map
      const growing = growth !== null && growth.age < 2.6;
      if (growing || growthChanged || Math.floor(t * 8) !== last) {
        last = Math.floor(t * 8);
        for (const f of ticks) f(t);
        growthChanged = false;
      }
    },
    grow: (next) => {
      growthChanged = growth?.kind !== next?.kind;
      growth = next;
    },
    setTelemetry: (data) => {
      telemetry = data;
      for (const paint of telemetryScreens) paint(0);
    },
    dispose: () => {
      for (const d of disposables) d.dispose();
    },
  };
}
