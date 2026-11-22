// The village's small effects, all pooled so a busy run allocates nothing per frame: sparks (the case file's
// light trail, a burst of light when a verdict lands or an action is verified) and ripples (a ring of light
// spreading over the snow when a case arrives, an alarm goes off, or the approval post calls you).

import { AdditiveBlending, Color, DoubleSide, Group, Mesh, MeshBasicMaterial, RingGeometry, Sprite, SpriteMaterial, Vector3 } from "three";
import { glowTexture, seeded } from "./util";

interface Spark {
  sprite: Sprite;
  material: SpriteMaterial;
  velocity: Vector3;
  age: number;
  life: number;
  size: number;
  /** pulls the spark down (bursts) or lets it float (trail) */
  gravity: number;
  drag: number;
}

/** Glowing points with a velocity and a life: trails and bursts. */
export class Sparks {
  readonly group = new Group();
  private readonly pool: Spark[] = [];
  private next = 0;
  private readonly color = new Color();
  private readonly rand = seeded(97);

  constructor(count = 96) {
    for (let i = 0; i < count; i++) {
      const material = new SpriteMaterial({ map: glowTexture(), transparent: true, depthWrite: false, blending: AdditiveBlending, toneMapped: false, opacity: 0 });
      const sprite = new Sprite(material);
      sprite.visible = false;
      sprite.renderOrder = 5;
      this.group.add(sprite);
      this.pool.push({ sprite, material, velocity: new Vector3(), age: 0, life: 0, size: 0, gravity: 0, drag: 0 });
    }
  }

  private take(): Spark {
    const s = this.pool[this.next];
    this.next = (this.next + 1) % this.pool.length;
    return s;
  }

  /** One spark at `p`: `v` units/s, `life` seconds, `size` units across, `hex` tinted and `heat` bright. */
  emit(p: Vector3, v: Vector3, life: number, size: number, hex: string, heat = 1.6, gravity = 0, drag = 1.2): void {
    const s = this.take();
    s.sprite.position.copy(p);
    s.velocity.copy(v);
    s.age = 0;
    s.life = life;
    s.size = size;
    s.gravity = gravity;
    s.drag = drag;
    s.material.color.copy(this.color.set(hex).multiplyScalar(heat));
    s.sprite.visible = true;
  }

  /** A fountain of `n` sparks rising from `p` and falling back, in `colors` by turns. */
  burst(p: Vector3, colors: string[], n = 26, power = 1): void {
    const rand = this.rand;
    for (let i = 0; i < n; i++) {
      const a = (i / n) * Math.PI * 2 + rand() * 0.4;
      const out = (0.7 + rand() * 1.1) * power;
      const up = (2.4 + rand() * 1.8) * power;
      this.emit(p, new Vector3(Math.cos(a) * out, up, Math.sin(a) * out * 0.7), 1.1 + rand() * 0.6, 0.16 + rand() * 0.14, colors[i % colors.length], 2.2, 4.2, 0.6);
    }
  }

  clear(): void {
    for (const s of this.pool) s.sprite.visible = false;
  }

  update(dt: number): void {
    for (const s of this.pool) {
      if (!s.sprite.visible) continue;
      s.age += dt;
      if (s.age >= s.life) {
        s.sprite.visible = false;
        continue;
      }
      s.velocity.y -= s.gravity * dt;
      s.velocity.multiplyScalar(Math.exp(-s.drag * dt));
      s.sprite.position.addScaledVector(s.velocity, dt);
      const k = s.age / s.life;
      // in fast, out slow; the trail's sparks shrink as they cool
      const fade = Math.min(1, s.age / 0.08) * (1 - k) * (1 - k);
      s.material.opacity = fade;
      s.sprite.scale.setScalar(s.size * (1 - 0.45 * k));
    }
  }

  dispose(): void {
    for (const s of this.pool) s.material.dispose();
  }
}

interface Ripple {
  mesh: Mesh;
  material: MeshBasicMaterial;
  age: number;
  life: number;
  from: number;
  to: number;
  strength: number;
}

/** Rings of light that spread over the snow and fade. */
export class Ripples {
  readonly group = new Group();
  private readonly pool: Ripple[] = [];
  private readonly geometry = new RingGeometry(0.86, 1, 48);
  private next = 0;

  constructor(count = 8) {
    this.geometry.rotateX(-Math.PI / 2);
    for (let i = 0; i < count; i++) {
      const material = new MeshBasicMaterial({ transparent: true, depthWrite: false, blending: AdditiveBlending, toneMapped: false, side: DoubleSide, opacity: 0 });
      const mesh = new Mesh(this.geometry, material);
      mesh.visible = false;
      mesh.renderOrder = 2;
      this.group.add(mesh);
      this.pool.push({ mesh, material, age: 0, life: 0, from: 0, to: 0, strength: 0 });
    }
  }

  /** A ring at `p` (on the ground) growing from `from` to `to` units across over `life` seconds. */
  emit(p: Vector3, hex: string, from = 0.4, to = 2.6, life = 1.1, strength = 1): void {
    const r = this.pool[this.next];
    this.next = (this.next + 1) % this.pool.length;
    r.mesh.position.set(p.x, 0.05, p.z);
    r.material.color.set(hex).multiplyScalar(1.8);
    r.age = 0;
    r.life = life;
    r.from = from;
    r.to = to;
    r.strength = strength;
    r.mesh.visible = true;
  }

  update(dt: number): void {
    for (const r of this.pool) {
      if (!r.mesh.visible) continue;
      r.age += dt;
      if (r.age >= r.life) {
        r.mesh.visible = false;
        continue;
      }
      const k = r.age / r.life;
      const grow = 1 - Math.pow(1 - k, 3);
      r.mesh.scale.setScalar(r.from + (r.to - r.from) * grow);
      r.material.opacity = r.strength * Math.min(1, k / 0.12) * (1 - k);
    }
  }

  clear(): void {
    for (const r of this.pool) r.mesh.visible = false;
  }

  dispose(): void {
    this.geometry.dispose();
    for (const r of this.pool) r.material.dispose();
  }
}
