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
import { AvatarPainter, OVERSCAN } from "../avatars/painter";
import { IDLE_AVATAR, type AvatarCue } from "../avatars/state";
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
  private dirty = true;
  private cue = IDLE_AVATAR;
  private readonly breathOffset: number;

  constructor(role: RoleId, seed: number, dpr: number, private readonly reduced: boolean) {
    this.role = role;
    this.dpr = dpr;
    this.breathOffset = seed * Math.PI * 2;
    this.painter = new AvatarPainter(PERSONAS[role], seed, reduced);
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

  setCue(cue: AvatarCue): void {
    if (cue.status === this.cue.status && cue.key === this.cue.key) return;
    this.cue = cue;
    this.painter.setStatus(cue.status, cue.key);
    this.dirty = true;
  }

  breathe(time: number): void {
    this.sprite.scale.y *= 0.99 + 0.01 * Math.cos(time * Math.PI / 2 + this.breathOffset);
  }

  /** Turns the head toward a direction on screen (x right, y up, about -1.5..1.5); strength 0 lets go. */
  look(x: number, y: number, strength: number): void {
    this.painter.sim.setPointer(x, y, strength);
  }

  /** A happy hop and a turn, now: a bot that receives a case. */
  poke(): void {
    this.painter.sim.poke();
  }

  /**
   * The walk: `phase` advances with the steps, `lean` (-1..1) tips the body into the direction of travel and
   * `amount` (0..1) blends the gait in and out. Returns how far the body is lifted off the snow this frame.
   */
  stride(phase: number, lean: number, amount: number): number {
    const bounce = Math.abs(Math.sin(phase));
    const contact = (1 - bounce) * amount;
    this.sprite.material.rotation = -lean * 0.16 * amount + Math.sin(phase) * 0.05 * amount;
    this.sprite.scale.set(BOT_SIZE * OVERSCAN * (1 + 0.07 * contact), BOT_SIZE * OVERSCAN * (1 - 0.07 * contact), 1);
    return bounce * 0.2 * amount;
  }

  /** Paint the working prop or a walking bot every frame, with slower updates for idle poses. */
  update(dt: number, walking: boolean): boolean {
    this.since += dt;
    const due = walking || this.painter.moving ? 0 : 1 / 20;
    if (!this.dirty && (this.reduced || this.since < due)) return false;
    this.painter.paint(this.ctx, PAINT_BOX, this.dpr, this.reduced ? 0 : this.since, this.cue.status === "waiting");
    this.since = 0;
    this.dirty = false;
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

  /** `scale` lets the file pop when it changes hands; `spin` turns it slowly while it rests on a desk. */
  place(p: Vector3, tilt: number, opacity: number, scale = 1, spin = 0): void {
    this.group.position.copy(p);
    this.group.rotation.set(tilt, spin, tilt * 0.4);
    this.group.scale.setScalar(scale);
    this.halo.opacity = 0.75 * opacity;
    this.group.visible = opacity > 0.02;
  }

  dispose(): void {
    this.geometry.dispose();
    this.body.dispose();
    this.halo.dispose();
  }
}
