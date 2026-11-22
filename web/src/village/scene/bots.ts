// The agents in the scene: each avatar (AvatarPainter, the same drawing as <AgentAvatar>) paints into a canvas
// that a sprite shows, so the plush bots keep their fur, turns and hops inside the 3D rooms. A bot that hands a
// case over walks it along the snow paths to the next igloo, carrying the glowing case file, and walks home.

import {
  AdditiveBlending,
  BoxGeometry,
  CanvasTexture,
  Color,
  Group,
  LinearFilter,
  Mesh,
  MeshBasicMaterial,
  SRGBColorSpace,
  Sprite,
  SpriteMaterial,
  Vector3,
} from "three";
import { AvatarPainter, OVERSCAN, type AvatarStatus } from "../avatars/painter";
import { PERSONAS } from "../avatars/personas";
import type { RoleId } from "../roles";
import { glowTexture } from "./util";

/** Body size of a bot in scene units. */
export const BOT_SIZE = 1.42;
/** CSS px of the body box the painter draws at (the canvas is OVERSCAN times this). */
const PAINT_BOX = 112;

export class Bot {
  readonly role: RoleId;
  readonly sprite: Sprite;
  readonly painter: AvatarPainter;
  private readonly canvas: HTMLCanvasElement;
  private readonly ctx: CanvasRenderingContext2D;
  private readonly texture: CanvasTexture;
  private readonly dpr: number;
  /** seconds since the last paint; idle bots paint at a lower rate */
  private since = 1;
  status: AvatarStatus = "idle";

  constructor(role: RoleId, seed: number, dpr: number) {
    this.role = role;
    this.dpr = dpr;
    this.painter = new AvatarPainter(PERSONAS[role], seed, false);
    this.canvas = document.createElement("canvas");
    const px = Math.round(PAINT_BOX * OVERSCAN * dpr);
    this.canvas.width = px;
    this.canvas.height = px;
    this.ctx = this.canvas.getContext("2d") as CanvasRenderingContext2D;
    this.texture = new CanvasTexture(this.canvas);
    this.texture.colorSpace = SRGBColorSpace;
    this.texture.minFilter = LinearFilter;
    this.texture.generateMipmaps = false;
    const material = new SpriteMaterial({ map: this.texture, transparent: true, alphaTest: 0.04, depthWrite: true, toneMapped: false });
    material.color.setScalar(1.08);
    this.sprite = new Sprite(material);
    // the canvas holds the body in its middle two thirds, lifted a tenth: anchor the sprite at the feet
    this.sprite.center.set(0.5, 0.1);
    this.sprite.scale.setScalar(BOT_SIZE * OVERSCAN);
    this.sprite.renderOrder = 3;
  }

  setStatus(status: AvatarStatus): void {
    this.status = status;
    this.painter.setStatus(status);
  }

  /** Paints when due: busy or walking bots every frame, the others about 20 times a second. */
  update(dt: number, busy: boolean): boolean {
    this.since += dt;
    const due = busy ? 0 : 1 / 20;
    if (this.since < due) return false;
    this.painter.paint(this.ctx, PAINT_BOX, this.dpr, this.since);
    this.since = 0;
    this.texture.needsUpdate = true;
    return true;
  }

  dispose(): void {
    this.texture.dispose();
    this.sprite.material.dispose();
  }
}

/** The case file: a glowing folder with a halo, carried, lying on a desk, or waiting at the approval post. */
export class CaseFile {
  readonly group = new Group();
  private readonly body: MeshBasicMaterial;
  private readonly halo: SpriteMaterial;
  private readonly geometry: BoxGeometry;
  private readonly tab: Mesh;

  constructor() {
    this.geometry = new BoxGeometry(0.42, 0.06, 0.32);
    this.body = new MeshBasicMaterial({ color: new Color("#6fb6ff").multiplyScalar(1.8), toneMapped: false });
    const folder = new Mesh(this.geometry, this.body);
    this.tab = new Mesh(this.geometry, this.body);
    this.tab.scale.set(0.35, 1, 0.2);
    this.tab.position.set(-0.12, 0.02, -0.17);
    this.halo = new SpriteMaterial({ map: glowTexture(), color: new Color("#8fc8ff"), transparent: true, depthWrite: false, blending: AdditiveBlending, opacity: 0.8 });
    const halo = new Sprite(this.halo);
    halo.scale.setScalar(1.3);
    this.group.add(folder, this.tab, halo);
    this.group.visible = false;
  }

  setColor(hex: string, intensity: number): void {
    this.body.color.set(hex).multiplyScalar(intensity);
    this.halo.color.set(hex);
  }

  place(p: Vector3, tilt: number, opacity: number): void {
    this.group.position.copy(p);
    this.group.rotation.set(tilt, 0, tilt * 0.4);
    this.halo.opacity = 0.75 * opacity;
    this.group.visible = opacity > 0.02;
  }

  dispose(): void {
    this.geometry.dispose();
    this.body.dispose();
    this.halo.dispose();
  }
}
