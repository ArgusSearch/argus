// All metric and log blocks in one instanced draw call (A8), plus their ground shadows in a second one.
// Per-instance state lives in typed arrays the engine writes every frame; nothing is allocated per frame.

import {
  CustomBlending,
  DynamicDrawUsage,
  InstancedBufferAttribute,
  InstancedMesh,
  Matrix4,
  OneFactor,
  OneMinusSrcAlphaFactor,
  PlaneGeometry,
  Quaternion,
  ShaderMaterial,
  Vector3,
} from "three";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import type { Env } from "./env";
import { BLOCK } from "./layout";
import { blockFragment, blockVertex, shadowFragment, shadowVertex } from "./shaders/block";

const IDENTITY = new Quaternion();

export const BLOCK_CAPACITY = 96;

export class Blocks {
  readonly mesh: InstancedMesh;
  readonly shadows: InstancedMesh;
  /** core light color, linear RGB */
  readonly core: Float32Array;
  /** glow, crack, materialize, dim */
  readonly state: Float32Array;
  /** highlight, refreeze flash, seed, log */
  readonly state2: Float32Array;
  readonly material: ShaderMaterial;
  readonly shadowMaterial: ShaderMaterial;
  private readonly coreAttr: InstancedBufferAttribute;
  private readonly stateAttr: InstancedBufferAttribute;
  private readonly state2Attr: InstancedBufferAttribute;
  private readonly matrix = new Matrix4();
  private readonly scale = new Vector3();
  private readonly pos = new Vector3();

  constructor(env: Env) {
    const geometry = new RoundedBoxGeometry(BLOCK[0], BLOCK[1], BLOCK[2], 3, 0.085);
    this.core = new Float32Array(BLOCK_CAPACITY * 3);
    this.state = new Float32Array(BLOCK_CAPACITY * 4);
    this.state2 = new Float32Array(BLOCK_CAPACITY * 4);
    this.coreAttr = new InstancedBufferAttribute(this.core, 3).setUsage(DynamicDrawUsage);
    this.stateAttr = new InstancedBufferAttribute(this.state, 4).setUsage(DynamicDrawUsage);
    this.state2Attr = new InstancedBufferAttribute(this.state2, 4).setUsage(DynamicDrawUsage);
    geometry.setAttribute("aCore", this.coreAttr);
    geometry.setAttribute("aState", this.stateAttr);
    geometry.setAttribute("aState2", this.state2Attr);

    this.material = new ShaderMaterial({
      vertexShader: blockVertex,
      fragmentShader: blockFragment,
      uniforms: {
        uTime: env.uTime,
        uFogColor: env.uFogColor,
        uFogNear: env.uFogNear,
        uFogDensity: env.uFogDensity,
        uHud: env.uHud,
        uHalf: { value: new Vector3(BLOCK[0] / 2, BLOCK[1] / 2, BLOCK[2] / 2) },
        uLit: { value: env.uFogColor.value.clone() },
        uShade: { value: env.uFogColor.value.clone() },
        uRim: { value: env.uHud.value.clone() },
        uLightDir: { value: new Vector3(-0.42, 1, 0.55).normalize() },
      },
    });
    this.mesh = new InstancedMesh(geometry, this.material, BLOCK_CAPACITY);
    this.mesh.instanceMatrix.setUsage(DynamicDrawUsage);
    this.mesh.count = 0;
    this.mesh.frustumCulled = false;
    this.mesh.renderOrder = 2;

    const plane = new PlaneGeometry(1, 1).rotateX(-Math.PI / 2);
    plane.setAttribute("aCore", this.coreAttr);
    plane.setAttribute("aState", this.stateAttr);
    this.shadowMaterial = new ShaderMaterial({
      vertexShader: shadowVertex,
      fragmentShader: shadowFragment,
      uniforms: {
        uFogColor: env.uFogColor,
        uFogNear: env.uFogNear,
        uFogDensity: env.uFogDensity,
        uShadow: { value: env.uFogColor.value.clone() },
        uShadowAlpha: { value: 0.4 },
      },
      transparent: true,
      depthWrite: false,
      blending: CustomBlending,
      blendSrc: OneFactor,
      blendDst: OneMinusSrcAlphaFactor,
    });
    this.shadows = new InstancedMesh(plane, this.shadowMaterial, BLOCK_CAPACITY);
    this.shadows.instanceMatrix.setUsage(DynamicDrawUsage);
    this.shadows.count = 0;
    this.shadows.frustumCulled = false;
    this.shadows.renderOrder = 1;
  }

  set count(n: number) {
    this.mesh.count = Math.min(n, BLOCK_CAPACITY);
    this.shadows.count = this.mesh.count;
  }

  get count(): number {
    return this.mesh.count;
  }

  /** Places block `i` (center `x, y, z`, scale `sx, sy, sz`) and its shadow. */
  place(i: number, x: number, y: number, z: number, sx: number, sy: number, sz: number): void {
    this.matrix.compose(this.pos.set(x, y, z), IDENTITY, this.scale.set(sx, sy, sz));
    this.mesh.setMatrixAt(i, this.matrix);
    const w = BLOCK[0] * sx * 1.5;
    const d = BLOCK[2] * sz * 2.6;
    this.matrix.compose(this.pos.set(x, 0.012, z + 0.12), IDENTITY, this.scale.set(w, 1, d));
    this.shadows.setMatrixAt(i, this.matrix);
  }

  commit(): void {
    this.mesh.instanceMatrix.needsUpdate = true;
    this.shadows.instanceMatrix.needsUpdate = true;
    this.coreAttr.needsUpdate = true;
    this.stateAttr.needsUpdate = true;
    this.state2Attr.needsUpdate = true;
  }

  dispose(): void {
    this.mesh.geometry.dispose();
    this.shadows.geometry.dispose();
    this.material.dispose();
    this.shadowMaterial.dispose();
    this.mesh.dispose();
    this.shadows.dispose();
  }
}
