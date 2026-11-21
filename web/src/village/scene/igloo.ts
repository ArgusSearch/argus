// The igloos, cut open toward the camera: domes of ice blocks with the front quarter removed, a warm plaster
// shell inside, a plank floor with a rug, and a warm light that makes the room glow against the cold snow.
// All blocks of all igloos are one instanced mesh with an icy sheen from the environment map.

import {
  BoxGeometry,
  CircleGeometry,
  Color,
  DoubleSide,
  Group,
  InstancedMesh,
  Matrix4,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Object3D,
  PointLight,
  SphereGeometry,

  type Texture,
} from "three";
import type { Role } from "../roles";
import { seeded } from "./util";

const BLOCK_H = 0.4;
const DEPTH = 0.36;
/** the opening toward the camera, radians of azimuth */
export const CUT = (128 * Math.PI) / 180;

interface Placement {
  x: number;
  y: number;
  z: number;
  ry: number;
  rx: number;
  sx: number;
  sy: number;
}

/** Block placements of one cut-open igloo, in its own frame (opening toward +z). */
export function domeBlocks(radius: number, seed: number): Placement[] {
  const rand = seeded(seed);
  const out: Placement[] = [];
  const rings = Math.max(4, Math.round((radius * Math.PI) / 2 / BLOCK_H) - 1);
  for (let k = 0; k < rings; k++) {
    const phi = ((k + 0.5) / (rings + 0.55)) * (Math.PI / 2);
    const ring = radius * Math.cos(phi);
    const width = 0.62;
    const n = Math.max(6, Math.round((2 * Math.PI * ring) / width));
    const offset = (k % 2) * (Math.PI / n);
    // the cut runs the full height: the dome reads as an arch over the room
    const cut = CUT * (1 + 0.15 * (k / rings));
    for (let i = 0; i < n; i++) {
      const theta = offset + (i / n) * Math.PI * 2;
      const x = Math.cos(theta) * ring;
      const z = Math.sin(theta) * ring;
      if (Math.abs(Math.atan2(x, z)) < cut / 2) continue;
      out.push({
        x,
        y: Math.sin(phi) * radius,
        z,
        ry: -theta + Math.PI / 2,
        rx: -phi,
        sx: ((2 * Math.PI * ring) / n / width) * (0.93 + rand() * 0.04),
        sy: 0.92 + rand() * 0.08,
      });
    }
  }
  return out;
}

export interface IglooVisual {
  role: Role;
  group: Group;
  light: PointLight;
  rug: MeshBasicMaterial;
  /** an invisible volume for picking */
  hit: Mesh;
  glow: number;
  flash: number;
}

export class Igloos {
  readonly group = new Group();
  readonly blocks: InstancedMesh;
  readonly ice: MeshStandardMaterial;
  readonly items: IglooVisual[] = [];
  private readonly disposables: { dispose(): void }[] = [];

  constructor(roles: readonly Role[], env: Texture | null) {
    const placements: { p: Placement; role: Role; tint: Color }[] = [];
    roles.forEach((role, i) => {
      const rand = seeded(31 + i);
      for (const p of domeBlocks(role.size, 101 + i * 17)) {
        const tint = new Color("#d4e2f4").lerp(new Color("#a6c0e4"), rand() * 0.7);
        placements.push({ p, role, tint });
      }
    });

    const geometry = new BoxGeometry(0.62, BLOCK_H * 0.92, DEPTH);
    geometry.translate(0, (BLOCK_H * 0.92) / 2, 0);
    this.ice = new MeshStandardMaterial({
      color: "#ffffff",
      roughness: 0.24,
      metalness: 0.02,
      envMap: env,
      envMapIntensity: 0.42,
      emissive: new Color("#8fb8f0"),
      emissiveIntensity: 0.06,
      flatShading: true,
    });
    this.blocks = new InstancedMesh(geometry, this.ice, placements.length);
    this.blocks.castShadow = true;
    this.blocks.receiveShadow = true;
    const local = new Object3D();
    local.rotation.order = "YXZ";
    const at = new Object3D();
    const m = new Matrix4();
    placements.forEach(({ p, role, tint }, i) => {
      local.position.set(p.x, p.y, p.z);
      local.rotation.set(p.rx, p.ry, 0);
      local.scale.set(p.sx, p.sy, 1);
      local.updateMatrix();
      at.position.set(role.x, 0, role.z);
      at.rotation.set(0, role.facing, 0);
      at.updateMatrix();
      m.multiplyMatrices(at.matrix, local.matrix);
      this.blocks.setMatrixAt(i, m);
      this.blocks.setColorAt(i, tint);
    });
    this.blocks.instanceMatrix.needsUpdate = true;
    if (this.blocks.instanceColor) this.blocks.instanceColor.needsUpdate = true;
    this.group.add(this.blocks);
    this.disposables.push(geometry, this.ice, this.blocks);

    const plaster = new MeshStandardMaterial({ color: "#e2c9a6", roughness: 0.92, metalness: 0, side: DoubleSide });
    const planks = new MeshStandardMaterial({ color: "#b98a5e", roughness: 0.8, metalness: 0 });
    const hitMaterial = new MeshBasicMaterial({ visible: false });
    this.disposables.push(plaster, planks, hitMaterial);

    for (const role of roles) {
      const inner = role.size - DEPTH * 0.55;
      const g = new Group();
      g.position.set(role.x, 0, role.z);
      g.rotation.y = role.facing;

      const shellGeo = new SphereGeometry(inner, 36, 14, Math.PI / 2 + CUT / 2, Math.PI * 2 - CUT, 0, Math.PI / 2);
      const shell = new Mesh(shellGeo, plaster);
      shell.receiveShadow = true;
      const floorGeo = new CircleGeometry(inner + 0.05, 40);
      const floor = new Mesh(floorGeo, planks);
      floor.rotation.x = -Math.PI / 2;
      floor.position.y = 0.02;
      floor.receiveShadow = true;
      const rugMat = new MeshBasicMaterial({ color: new Color(role.color).lerp(new Color("#f3e6d2"), 0.55) });
      const rugGeo = new CircleGeometry(inner * 0.55, 32);
      const rug = new Mesh(rugGeo, rugMat);
      rug.rotation.x = -Math.PI / 2;
      rug.scale.set(1.35, 0.8, 1);
      rug.position.set(0, 0.035, 0.15);

      const light = new PointLight("#ffbf7a", 9, inner * 2.6, 1.6);
      light.position.set(0, inner * 0.82, -0.2);

      const hitGeo = new SphereGeometry(1, 10, 6);
      const hit = new Mesh(hitGeo, hitMaterial);
      hit.scale.set(role.size * 1.05, role.size * 1.05, role.size * 1.1);
      hit.userData.role = role.id;

      g.add(shell, floor, rug, light, hit);
      this.group.add(g);
      this.disposables.push(shellGeo, floorGeo, rugGeo, rugMat, hitGeo);
      this.items.push({ role, group: g, light, rug: rugMat, hit, glow: 0.4, flash: 0 });
    }
  }

  /** The room lights: brighter while the role works, a short flash when it receives a case. */
  update(dt: number, levels: Map<string, number>, time: number): void {
    for (const it of this.items) {
      const target = levels.get(it.role.id) ?? 0.3;
      it.glow += (target - it.glow) * (1 - Math.exp(-3 * dt));
      it.flash = Math.max(0, it.flash - dt * 1.2);
      const flicker = 1 + Math.sin(time * 2.1 + it.role.x) * 0.03 + Math.sin(time * 6.7 + it.role.z) * 0.015;
      it.light.intensity = (3.2 + it.glow * 4.6 + it.flash * 6) * flicker;
    }
  }

  dispose(): void {
    for (const d of this.disposables) d.dispose();
  }
}

