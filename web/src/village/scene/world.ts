// The land around the igloos: a snowy plateau that falls away into the fog, far mountains, snowy pines, the
// trodden paths that meet in the plaza, lamp posts, the approval post with its lantern, and falling snow.
// The routes the bots walk are the same curves the paths are drawn from.

import {
  AdditiveBlending,
  BufferAttribute,
  BufferGeometry,
  CatmullRomCurve3,
  Color,
  ConeGeometry,
  CylinderGeometry,
  Group,
  IcosahedronGeometry,
  InstancedMesh,
  Mesh,
  MeshBasicMaterial,
  MeshStandardMaterial,
  Object3D,
  PlaneGeometry,
  Points,
  ShaderMaterial,
  SphereGeometry,
  Vector3,

} from "three";
import { APPROVAL_POST, ROLE, ROLES, type RoleId } from "../roles";
import { glowTexture, seeded } from "./util";

/** The plaza where the paths meet. */
export const PLAZA = new Vector3(0, 0, 0.2);

/** Just outside a role's opening, where its path starts. */
export function doorPoint(id: RoleId): Vector3 {
  const r = ROLE[id];
  return new Vector3(r.x + Math.sin(r.facing) * (r.size + 0.55), 0, r.z + Math.cos(r.facing) * (r.size + 0.55));
}

/** Inside a role's room, where its bot works. */
export function seatPoint(id: RoleId): Vector3 {
  const r = ROLE[id];
  return new Vector3(r.x, 0, r.z - 0.25);
}

/**
 * From a role's door to the plaza. Igloos in the front row open toward the camera, away from the plaza, so
 * their path first rounds the igloo on the plaza side.
 */
export function toPlaza(id: RoleId): Vector3[] {
  const r = ROLE[id];
  const door = doorPoint(id);
  if (r.z < 3) return [door, PLAZA.clone()];
  const side = new Vector3(r.x - Math.sign(r.x) * (r.size + 0.75), 0, r.z + 0.6);
  return [door, side, PLAZA.clone()];
}

const curves = new Map<string, CatmullRomCurve3>();

/** The walk from one room to another: out of the door, through the plaza (unless they are neighbours), in. */
export function route(a: RoleId, b: RoleId): CatmullRomCurve3 {
  const key = `${a}>${b}`;
  let c = curves.get(key);
  if (!c) {
    const out = toPlaza(a);
    const back = toPlaza(b).reverse();
    // meet near the plaza, not at its centre, so two walkers do not cross through one point
    const meet = out[out.length - 1].clone().lerp(out[out.length - 2], 0.35).lerp(back[1], 0.35);
    c = new CatmullRomCurve3([seatPoint(a), ...out.slice(0, -1), meet, ...back.slice(1), seatPoint(b)], false, "centripetal");
    curves.set(key, c);
  }
  return c;
}

/** The height of the snow at (x, z): flat on the plateau, falling away past its rim. */
export function terrain(x: number, z: number): number {
  const r = Math.hypot(x / 15.5, (z - 0.2) / 12.5);
  const fall = Math.max(0, r - 1) * 9;
  const n = Math.sin(x * 0.31 + 1.3) * Math.cos(z * 0.27 - 0.4) * 0.12;
  return -fall * fall * 0.5 + n * Math.min(1, r);
}

export class World {
  readonly group = new Group();
  readonly snow: Points;
  readonly snowMaterial: ShaderMaterial;
  readonly lantern: MeshBasicMaterial;
  readonly lanternHalo: MeshBasicMaterial;
  readonly lanternPost: Group;
  private readonly lamps: MeshBasicMaterial;
  private readonly disposables: { dispose(): void }[] = [];

  constructor() {
    const rand = seeded(7);
    const o = new Object3D();
    const track = <T extends { dispose(): void }>(x: T) => {
      this.disposables.push(x);
      return x;
    };

    // the plateau
    const ground = track(new PlaneGeometry(90, 80, 90, 80));
    ground.rotateX(-Math.PI / 2);
    const pos = ground.attributes.position as BufferAttribute;
    for (let i = 0; i < pos.count; i++) pos.setY(i, terrain(pos.getX(i), pos.getZ(i)));
    ground.computeVertexNormals();
    const snowMat = track(new MeshStandardMaterial({ color: "#f1f4f9", roughness: 0.95, metalness: 0 }));
    const groundMesh = new Mesh(ground, snowMat);
    groundMesh.receiveShadow = true;
    this.group.add(groundMesh);

    // rocks along the rim of the plateau
    const rock = track(new IcosahedronGeometry(1, 0));
    const rockMat = track(new MeshStandardMaterial({ color: "#b7bfcc", roughness: 0.9, flatShading: true }));
    const rocks = track(new InstancedMesh(rock, rockMat, 46));
    for (let i = 0; i < 46; i++) {
      const a = (i / 46) * Math.PI * 2;
      const x = Math.cos(a) * 15.8 + (rand() - 0.5);
      const z = Math.sin(a) * 12.8 + 0.2 + (rand() - 0.5);
      o.position.set(x, terrain(x, z) - 0.3, z);
      o.scale.set(0.4 + rand() * 0.6, 0.3 + rand() * 0.4, 0.4 + rand() * 0.6);
      o.rotation.set(rand(), rand() * 6, rand());
      o.updateMatrix();
      rocks.setMatrixAt(i, o.matrix);
    }
    rocks.castShadow = true;
    this.group.add(rocks);

    // far mountains in the fog
    const peak = track(new ConeGeometry(1, 1, 5, 1));
    peak.translate(0, 0.5, 0);
    const peakMat = track(new MeshStandardMaterial({ color: "#c7cdd9", roughness: 1, flatShading: true }));
    const peaks = track(new InstancedMesh(peak, peakMat, 22));
    for (let i = 0; i < 22; i++) {
      const a = -1.2 + (i / 21) * 2.4;
      const dist = 62 + rand() * 18;
      o.position.set(Math.sin(a) * dist * 1.2, -10, -Math.cos(a) * dist - 8);
      const h = 10 + rand() * 12;
      o.scale.set(h * (0.8 + rand() * 0.5), h, h * 0.8);
      o.rotation.set(0, rand() * Math.PI, 0);
      o.updateMatrix();
      peaks.setMatrixAt(i, o.matrix);
    }
    this.group.add(peaks);

    // snowy pines between and around the igloos
    const pine = track(new ConeGeometry(0.7, 1.7, 7, 1));
    pine.translate(0, 1.25, 0);
    const pineTop = track(new ConeGeometry(0.5, 1.2, 7, 1));
    pineTop.translate(0, 2.05, 0);
    const trunk = track(new CylinderGeometry(0.1, 0.13, 0.45, 6));
    trunk.translate(0, 0.22, 0);
    const pineMat = track(new MeshStandardMaterial({ color: "#56747f", roughness: 0.9, flatShading: true }));
    const capMat = track(new MeshStandardMaterial({ color: "#f8fafd", roughness: 0.9, flatShading: true }));
    const trunkMat = track(new MeshStandardMaterial({ color: "#6b5649", roughness: 1, flatShading: true }));
    const spots: [number, number, number][] = [];
    for (let i = 0; i < 400 && spots.length < 30; i++) {
      const x = (rand() - 0.5) * 34;
      const z = -11.5 + rand() * 23;
      const r = Math.hypot(x / 15.5, (z - 0.2) / 12.5);
      if (r > 1.02) continue;
      const clearOfIgloos = ROLES.every((ro) => Math.hypot(ro.x - x, ro.z + 0.6 - z) > ro.size + 1.5);
      const clearOfPaths = Math.hypot(x - PLAZA.x, z - PLAZA.z) > 3.2 && Math.abs(x) > 1.4;
      const nearEdge = r > 0.72;
      if (clearOfIgloos && clearOfPaths && (nearEdge || rand() < 0.25)) spots.push([x, z, 0.65 + rand() * 0.75]);
    }
    const pines = track(new InstancedMesh(pine, pineMat, spots.length));
    const caps = track(new InstancedMesh(pineTop, capMat, spots.length));
    const trunks = track(new InstancedMesh(trunk, trunkMat, spots.length));
    spots.forEach(([x, z, s], i) => {
      o.position.set(x, terrain(x, z) - 0.05, z);
      o.scale.setScalar(s);
      o.rotation.set(0, rand() * 6, 0);
      o.updateMatrix();
      pines.setMatrixAt(i, o.matrix);
      caps.setMatrixAt(i, o.matrix);
      trunks.setMatrixAt(i, o.matrix);
    });
    for (const m of [pines, caps, trunks]) {
      m.castShadow = true;
      this.group.add(m);
    }

    // trodden paths: pressed, slightly blue snow from each door to the plaza
    const trodden = track(new MeshStandardMaterial({ color: "#d6deea", roughness: 1 }));
    const step = track(new CylinderGeometry(0.42, 0.42, 0.02, 12));
    const steps: Vector3[] = [];
    for (const r of ROLES) {
      const c = new CatmullRomCurve3(toPlaza(r.id), false, "centripetal");
      const n = Math.round(c.getLength() / 0.3);
      for (let i = 0; i <= n; i++) steps.push(c.getPointAt(i / n));
    }
    const paths = track(new InstancedMesh(step, trodden, steps.length));
    steps.forEach((p, i) => {
      o.position.set(p.x, 0.012, p.z);
      o.scale.set(1, 1, 1);
      o.rotation.set(0, 0, 0);
      o.updateMatrix();
      paths.setMatrixAt(i, o.matrix);
    });
    paths.receiveShadow = true;
    this.group.add(paths);
    const plaza = new Mesh(track(new CylinderGeometry(1.9, 1.9, 0.02, 32)), trodden);
    plaza.position.copy(PLAZA).setY(0.014);
    plaza.receiveShadow = true;
    this.group.add(plaza);

    // little lamp posts along the paths
    this.lamps = track(new MeshBasicMaterial({ color: new Color("#ffcf8a").multiplyScalar(2.2), toneMapped: false }));
    const postGeo = track(new CylinderGeometry(0.05, 0.06, 0.55, 6));
    postGeo.translate(0, 0.27, 0);
    const bulbGeo = track(new SphereGeometry(0.09, 10, 8));
    const postMat = track(new MeshStandardMaterial({ color: "#5b4d43", roughness: 0.8 }));
    const haloGeo = track(new PlaneGeometry(1, 1));
    const haloMat = track(new MeshBasicMaterial({ map: glowTexture(), color: new Color("#ffc983"), transparent: true, opacity: 0.35, depthWrite: false, blending: AdditiveBlending, toneMapped: false }));
    for (const r of ROLES) {
      const way = toPlaza(r.id);
      const p = way[way.length - 2].clone().lerp(PLAZA, 0.42).add(new Vector3(0.55, 0, 0));
      const post = new Mesh(postGeo, postMat);
      post.position.copy(p);
      post.castShadow = true;
      const bulb = new Mesh(bulbGeo, this.lamps);
      bulb.position.copy(p).setY(0.62);
      const halo = new Mesh(haloGeo, haloMat);
      halo.rotation.x = -Math.PI / 2;
      halo.position.copy(p).setY(0.03);
      halo.scale.setScalar(1.6);
      this.group.add(post, bulb, halo);
    }

    // the approval post: a wooden post with a lantern that glows while a case waits for you
    this.lanternPost = new Group();
    this.lanternPost.position.set(APPROVAL_POST[0], 0, APPROVAL_POST[1]);
    const wood = track(new MeshStandardMaterial({ color: "#6e5443", roughness: 0.85, flatShading: true }));
    const poleGeo = track(new CylinderGeometry(0.07, 0.09, 2.1, 6));
    poleGeo.translate(0, 1.05, 0);
    const pole = new Mesh(poleGeo, wood);
    pole.castShadow = true;
    const armGeo = track(new CylinderGeometry(0.04, 0.04, 0.6, 6));
    const arm = new Mesh(armGeo, wood);
    arm.rotation.z = Math.PI / 2;
    arm.position.set(0.28, 2.0, 0);
    this.lantern = track(new MeshBasicMaterial({ color: new Color("#ffcf8a"), toneMapped: false }));
    const lampGeo = track(new CylinderGeometry(0.13, 0.11, 0.28, 6));
    const lamp = new Mesh(lampGeo, this.lantern);
    lamp.position.set(0.52, 1.78, 0);
    const capGeo = track(new ConeGeometry(0.17, 0.12, 6));
    const cap = new Mesh(capGeo, wood);
    cap.position.set(0.52, 1.98, 0);
    this.lanternHalo = track(new MeshBasicMaterial({ map: glowTexture(), color: new Color("#ff8a6a"), transparent: true, depthWrite: false, blending: AdditiveBlending, opacity: 0, toneMapped: false }));
    const halo = new Mesh(haloGeo, this.lanternHalo);
    halo.rotation.x = -Math.PI / 2;
    halo.position.set(0.4, 0.04, 0);
    halo.scale.setScalar(3.6);
    this.lanternPost.add(pole, arm, lamp, cap, halo);
    this.group.add(this.lanternPost);

    // falling snow
    this.snowMaterial = track(
      new ShaderMaterial({
        uniforms: { uTime: { value: 0 }, uColor: { value: new Color("#ffffff") }, uAlpha: { value: 0.8 }, uScale: { value: 1 } },
        vertexShader: /* glsl */ `
          attribute float aSeed;
          uniform float uTime;
          uniform float uScale;
          varying float vFade;
          void main() {
            vec3 p = position;
            p.y = mod(p.y - uTime * (0.45 + aSeed * 0.45), 14.0) - 0.5;
            p.x += sin(uTime * 0.5 + aSeed * 40.0) * 0.45 + uTime * 0.12;
            p.x = mod(p.x + 24.0, 48.0) - 24.0;
            p.z += cos(uTime * 0.37 + aSeed * 23.0) * 0.35;
            vec4 mv = modelViewMatrix * vec4(p, 1.0);
            gl_Position = projectionMatrix * mv;
            gl_PointSize = uScale * (1.4 + aSeed * 2.6) * (60.0 / -mv.z);
            vFade = smoothstep(-0.5, 1.0, p.y) * smoothstep(13.5, 10.0, p.y);
          }`,
        fragmentShader: /* glsl */ `
          uniform vec3 uColor;
          uniform float uAlpha;
          varying float vFade;
          void main() {
            float d = length(gl_PointCoord - 0.5);
            float a = smoothstep(0.5, 0.08, d) * uAlpha * vFade;
            if (a < 0.01) discard;
            gl_FragColor = vec4(uColor * 1.2, a);
          }`,
        transparent: true,
        depthWrite: false,
      }),
    );
    const count = 1600;
    const snowGeo = track(new BufferGeometry());
    const positions = new Float32Array(count * 3);
    const seeds = new Float32Array(count);
    for (let i = 0; i < count; i++) {
      positions[i * 3] = (rand() - 0.5) * 48;
      positions[i * 3 + 1] = rand() * 14;
      positions[i * 3 + 2] = -16 + rand() * 32;
      seeds[i] = rand();
    }
    snowGeo.setAttribute("position", new BufferAttribute(positions, 3));
    snowGeo.setAttribute("aSeed", new BufferAttribute(seeds, 1));
    this.snow = new Points(snowGeo, this.snowMaterial);
    this.snow.frustumCulled = false;
    this.snow.renderOrder = 6;
    this.group.add(this.snow);
  }

  setSnow(count: number): void {
    this.snow.geometry.setDrawRange(0, count);
    this.snow.visible = count > 0;
  }

  update(time: number, waiting: boolean): void {
    this.snowMaterial.uniforms.uTime.value = time;
    const pulse = waiting ? 0.7 + Math.sin(time * 4.2) * 0.3 : 0;
    this.lantern.color.set(waiting ? "#ff9a7a" : "#ffcf8a").multiplyScalar(waiting ? 2.2 + pulse * 2.4 : 1.3);
    this.lanternHalo.opacity = waiting ? 0.35 + 0.35 * pulse : 0;
  }

  dispose(): void {
    for (const d of this.disposables) d.dispose();
  }
}

