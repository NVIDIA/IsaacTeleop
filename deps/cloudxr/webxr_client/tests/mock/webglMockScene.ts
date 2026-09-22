/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 *
 * Unless required by applicable law or agreed to in writing, software
 * distributed under the License is distributed on an "AS IS" BASIS,
 * WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
 * See the License for the specific language governing permissions and
 * limitations under the License.
 */

/**
 * Minimal, dependency-free WebGL2 renderer for MockCloudXR's placeholder scene: a floor, a
 * spinning cube, a static pillar, and two controller-tracked shapes (torus/sphere), lit by a
 * single constant world-space directional light (N.L diffuse + a flat ambient term).
 *
 * Deliberately not three.js: MockCloudXR shares its `gl` context with the real app's own
 * react-three-fiber renderer (CloudXRComponent.tsx passes `useThree().gl` through as
 * `SessionOptions.gl`). A second `THREE.WebGLRenderer` wrapping that same context keeps its own
 * independent JS-side state cache, which drifts out of sync with r3f's cache as soon as either
 * one changes real GL state - CloudXRComponent's onWebGLStateChangeBegin/End save/restore
 * (WebGLStateBinding.ts) only reconciles actual GL state, not a second renderer's private
 * bookkeeping. Plain `gl.*` calls have no such cache, so they compose cleanly with that
 * save/restore (WebGLStateBinding monkey-patches state-mutating methods directly on the `gl`
 * object passed in, so any caller touching that same object - including us - gets tracked).
 */

/** Column-major 4x4 matrix, matching WebXR's `XRRigidTransform.matrix`/`XRView.projectionMatrix`. */
export type Mat4 = Float32Array;

function mat4Identity(): Mat4 {
  // prettier-ignore
  return new Float32Array([
    1, 0, 0, 0,
    0, 1, 0, 0,
    0, 0, 1, 0,
    0, 0, 0, 1,
  ]);
}

function mat4Multiply(a: Mat4, b: Mat4): Mat4 {
  const out = new Float32Array(16);
  for (let col = 0; col < 4; col++) {
    for (let row = 0; row < 4; row++) {
      let sum = 0;
      for (let k = 0; k < 4; k++) {
        sum += a[k * 4 + row] * b[col * 4 + k];
      }
      out[col * 4 + row] = sum;
    }
  }
  return out;
}

function mat4Translation(x: number, y: number, z: number): Mat4 {
  const m = mat4Identity();
  m[12] = x;
  m[13] = y;
  m[14] = z;
  return m;
}

function mat4RotationX(rad: number): Mat4 {
  const c = Math.cos(rad);
  const s = Math.sin(rad);
  const m = mat4Identity();
  m[5] = c;
  m[6] = s;
  m[9] = -s;
  m[10] = c;
  return m;
}

function mat4RotationY(rad: number): Mat4 {
  const c = Math.cos(rad);
  const s = Math.sin(rad);
  const m = mat4Identity();
  m[0] = c;
  m[2] = -s;
  m[8] = s;
  m[10] = c;
  return m;
}

function mat4RotationZ(rad: number): Mat4 {
  const c = Math.cos(rad);
  const s = Math.sin(rad);
  const m = mat4Identity();
  m[0] = c;
  m[1] = s;
  m[4] = -s;
  m[5] = c;
  return m;
}

/**
 * Inverts a rigid transform (rotation + translation, no scale) - always true of
 * `XRView.transform.matrix` per the WebXR spec. R^-1 = R^T, t' = -R^T * t; cheaper and simpler
 * than a general 4x4 inverse, and doesn't depend on getting a cofactor-expansion formula right.
 */
function mat4InvertRigid(m: Mat4): Mat4 {
  const out = new Float32Array(16);
  // Transpose the rotation 3x3 (columns <-> rows).
  out[0] = m[0];
  out[1] = m[4];
  out[2] = m[8];
  out[4] = m[1];
  out[5] = m[5];
  out[6] = m[9];
  out[8] = m[2];
  out[9] = m[6];
  out[10] = m[10];
  out[15] = 1;
  const tx = m[12];
  const ty = m[13];
  const tz = m[14];
  out[12] = -(m[0] * tx + m[1] * ty + m[2] * tz);
  out[13] = -(m[4] * tx + m[5] * ty + m[6] * tz);
  out[14] = -(m[8] * tx + m[9] * ty + m[10] * tz);
  return out;
}

/** Rotates vector v by quaternion q, without building a matrix (v' = v + 2w(q_xyz x v) + 2(q_xyz x (q_xyz x v))). */
export function rotateVectorByQuaternion(
  qx: number,
  qy: number,
  qz: number,
  qw: number,
  vx: number,
  vy: number,
  vz: number
): [number, number, number] {
  const uvx = qy * vz - qz * vy;
  const uvy = qz * vx - qx * vz;
  const uvz = qx * vy - qy * vx;
  const uuvx = qy * uvz - qz * uvy;
  const uuvy = qz * uvx - qx * uvz;
  const uuvz = qx * uvy - qy * uvx;
  return [vx + 2 * (qw * uvx + uuvx), vy + 2 * (qw * uvy + uuvy), vz + 2 * (qw * uvz + uuvz)];
}

interface MeshData {
  positions: Float32Array;
  normals: Float32Array;
  indices: Uint16Array;
}

function buildPlane(size: number): MeshData {
  const h = size / 2;
  // prettier-ignore
  return {
    positions: new Float32Array([-h, 0, -h, h, 0, -h, h, 0, h, -h, 0, h]),
    normals: new Float32Array([0, 1, 0, 0, 1, 0, 0, 1, 0, 0, 1, 0]),
    indices: new Uint16Array([0, 1, 2, 0, 2, 3]),
  };
}

function buildBox(hx: number, hy: number, hz: number): MeshData {
  const faces: Array<{ normal: [number, number, number]; verts: [number, number, number][] }> = [
    {
      normal: [0, 0, 1],
      verts: [
        [-hx, -hy, hz],
        [hx, -hy, hz],
        [hx, hy, hz],
        [-hx, hy, hz],
      ],
    },
    {
      normal: [0, 0, -1],
      verts: [
        [hx, -hy, -hz],
        [-hx, -hy, -hz],
        [-hx, hy, -hz],
        [hx, hy, -hz],
      ],
    },
    {
      normal: [1, 0, 0],
      verts: [
        [hx, -hy, hz],
        [hx, -hy, -hz],
        [hx, hy, -hz],
        [hx, hy, hz],
      ],
    },
    {
      normal: [-1, 0, 0],
      verts: [
        [-hx, -hy, -hz],
        [-hx, -hy, hz],
        [-hx, hy, hz],
        [-hx, hy, -hz],
      ],
    },
    {
      normal: [0, 1, 0],
      verts: [
        [-hx, hy, hz],
        [hx, hy, hz],
        [hx, hy, -hz],
        [-hx, hy, -hz],
      ],
    },
    {
      normal: [0, -1, 0],
      verts: [
        [-hx, -hy, -hz],
        [hx, -hy, -hz],
        [hx, -hy, hz],
        [-hx, -hy, hz],
      ],
    },
  ];

  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];
  faces.forEach((face, fi) => {
    const base = fi * 4;
    face.verts.forEach(v => {
      positions.push(...v);
      normals.push(...face.normal);
    });
    indices.push(base, base + 1, base + 2, base, base + 2, base + 3);
  });

  return {
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    indices: new Uint16Array(indices),
  };
}

function buildSphere(radius: number, latBands = 16, lonBands = 24): MeshData {
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];

  for (let lat = 0; lat <= latBands; lat++) {
    const theta = (lat * Math.PI) / latBands;
    const sinTheta = Math.sin(theta);
    const cosTheta = Math.cos(theta);
    for (let lon = 0; lon <= lonBands; lon++) {
      const phi = (lon * 2 * Math.PI) / lonBands;
      const x = Math.cos(phi) * sinTheta;
      const y = cosTheta;
      const z = Math.sin(phi) * sinTheta;
      positions.push(radius * x, radius * y, radius * z);
      normals.push(x, y, z);
    }
  }

  for (let lat = 0; lat < latBands; lat++) {
    for (let lon = 0; lon < lonBands; lon++) {
      const first = lat * (lonBands + 1) + lon;
      const second = first + lonBands + 1;
      indices.push(first, second, first + 1);
      indices.push(second, second + 1, first + 1);
    }
  }

  return {
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    indices: new Uint16Array(indices),
  };
}

function buildTorus(
  radius: number,
  tube: number,
  radialSegments = 12,
  tubularSegments = 24
): MeshData {
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];

  for (let j = 0; j <= radialSegments; j++) {
    for (let i = 0; i <= tubularSegments; i++) {
      const u = (i / tubularSegments) * Math.PI * 2;
      const v = (j / radialSegments) * Math.PI * 2;
      const cx = radius * Math.cos(u);
      const cz = radius * Math.sin(u);
      const x = (radius + tube * Math.cos(v)) * Math.cos(u);
      const y = tube * Math.sin(v);
      const z = (radius + tube * Math.cos(v)) * Math.sin(u);
      positions.push(x, y, z);
      const nx = x - cx;
      const ny = y;
      const nz = z - cz;
      const len = Math.hypot(nx, ny, nz) || 1;
      normals.push(nx / len, ny / len, nz / len);
    }
  }

  for (let j = 1; j <= radialSegments; j++) {
    for (let i = 1; i <= tubularSegments; i++) {
      const a = (tubularSegments + 1) * j + i - 1;
      const b = (tubularSegments + 1) * (j - 1) + i - 1;
      const c = (tubularSegments + 1) * (j - 1) + i;
      const d = (tubularSegments + 1) * j + i;
      indices.push(a, b, d);
      indices.push(b, c, d);
    }
  }

  return {
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    indices: new Uint16Array(indices),
  };
}

function buildCylinder(radius: number, height: number, segments = 16): MeshData {
  const positions: number[] = [];
  const normals: number[] = [];
  const indices: number[] = [];
  const halfHeight = height / 2;

  for (let i = 0; i <= segments; i++) {
    const theta = (i / segments) * Math.PI * 2;
    const x = Math.cos(theta);
    const z = Math.sin(theta);
    positions.push(radius * x, halfHeight, radius * z);
    normals.push(x, 0, z);
    positions.push(radius * x, -halfHeight, radius * z);
    normals.push(x, 0, z);
  }
  for (let i = 0; i < segments; i++) {
    const top1 = i * 2;
    const bottom1 = i * 2 + 1;
    const top2 = (i + 1) * 2;
    const bottom2 = (i + 1) * 2 + 1;
    indices.push(top1, bottom1, top2);
    indices.push(bottom1, bottom2, top2);
  }

  const topCenterIdx = positions.length / 3;
  positions.push(0, halfHeight, 0);
  normals.push(0, 1, 0);
  const topRingStart = topCenterIdx + 1;
  for (let i = 0; i <= segments; i++) {
    const theta = (i / segments) * Math.PI * 2;
    positions.push(radius * Math.cos(theta), halfHeight, radius * Math.sin(theta));
    normals.push(0, 1, 0);
  }
  for (let i = 0; i < segments; i++) {
    indices.push(topCenterIdx, topRingStart + i, topRingStart + i + 1);
  }

  const bottomCenterIdx = positions.length / 3;
  positions.push(0, -halfHeight, 0);
  normals.push(0, -1, 0);
  const bottomRingStart = bottomCenterIdx + 1;
  for (let i = 0; i <= segments; i++) {
    const theta = (i / segments) * Math.PI * 2;
    positions.push(radius * Math.cos(theta), -halfHeight, radius * Math.sin(theta));
    normals.push(0, -1, 0);
  }
  for (let i = 0; i < segments; i++) {
    indices.push(bottomCenterIdx, bottomRingStart + i + 1, bottomRingStart + i);
  }

  return {
    positions: new Float32Array(positions),
    normals: new Float32Array(normals),
    indices: new Uint16Array(indices),
  };
}

const VERTEX_SHADER = `#version 300 es
in vec3 aPosition;
in vec3 aNormal;
uniform mat4 uModel;
uniform mat4 uView;
uniform mat4 uProjection;
out vec3 vNormal;
void main() {
  // No non-uniform scale anywhere in this scene, so mat3(uModel) is a valid normal transform.
  vNormal = mat3(uModel) * aNormal;
  gl_Position = uProjection * uView * uModel * vec4(aPosition, 1.0);
}
`;

const FRAGMENT_SHADER = `#version 300 es
precision mediump float;
in vec3 vNormal;
uniform vec3 uColor;
uniform vec3 uLightDir;
out vec4 fragColor;
void main() {
  vec3 n = normalize(vNormal);
  float ndotl = max(dot(n, uLightDir), 0.0);
  fragColor = vec4(uColor * (0.3 + 0.8 * ndotl), 1.0);
}
`;

function compileShader(gl: WebGL2RenderingContext, type: number, source: string): WebGLShader {
  const shader = gl.createShader(type);
  if (!shader) {
    throw new Error('WebGLMockScene: gl.createShader failed');
  }
  gl.shaderSource(shader, source);
  gl.compileShader(shader);
  if (!gl.getShaderParameter(shader, gl.COMPILE_STATUS)) {
    const info = gl.getShaderInfoLog(shader);
    gl.deleteShader(shader);
    throw new Error(`WebGLMockScene: shader compile failed: ${info}`);
  }
  return shader;
}

function createProgram(gl: WebGL2RenderingContext): WebGLProgram {
  const vs = compileShader(gl, gl.VERTEX_SHADER, VERTEX_SHADER);
  const fs = compileShader(gl, gl.FRAGMENT_SHADER, FRAGMENT_SHADER);
  const program = gl.createProgram();
  if (!program) {
    throw new Error('WebGLMockScene: gl.createProgram failed');
  }
  gl.attachShader(program, vs);
  gl.attachShader(program, fs);
  gl.linkProgram(program);
  gl.deleteShader(vs);
  gl.deleteShader(fs);
  if (!gl.getProgramParameter(program, gl.LINK_STATUS)) {
    const info = gl.getProgramInfoLog(program);
    gl.deleteProgram(program);
    throw new Error(`WebGLMockScene: program link failed: ${info}`);
  }
  return program;
}

interface GLMesh {
  vao: WebGLVertexArrayObject;
  indexCount: number;
}

function uploadMesh(gl: WebGL2RenderingContext, program: WebGLProgram, data: MeshData): GLMesh {
  const vao = gl.createVertexArray();
  if (!vao) {
    throw new Error('WebGLMockScene: gl.createVertexArray failed');
  }
  gl.bindVertexArray(vao);

  const positionLoc = gl.getAttribLocation(program, 'aPosition');
  const positionBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, positionBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, data.positions, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(positionLoc);
  gl.vertexAttribPointer(positionLoc, 3, gl.FLOAT, false, 0, 0);

  const normalLoc = gl.getAttribLocation(program, 'aNormal');
  const normalBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ARRAY_BUFFER, normalBuffer);
  gl.bufferData(gl.ARRAY_BUFFER, data.normals, gl.STATIC_DRAW);
  gl.enableVertexAttribArray(normalLoc);
  gl.vertexAttribPointer(normalLoc, 3, gl.FLOAT, false, 0, 0);

  // Must stay bound while the VAO is bound - the element array binding is part of VAO state.
  const indexBuffer = gl.createBuffer();
  gl.bindBuffer(gl.ELEMENT_ARRAY_BUFFER, indexBuffer);
  gl.bufferData(gl.ELEMENT_ARRAY_BUFFER, data.indices, gl.STATIC_DRAW);

  gl.bindVertexArray(null);
  gl.bindBuffer(gl.ARRAY_BUFFER, null);

  return { vao, indexCount: data.indices.length };
}

/** Average standing eye height (m); matches a 'local' reference space, whose origin is at the
 * headset rather than the floor, so the scene reads correctly whether or not floor tracking
 * ('local-floor') is available. */
const SCENE_ORIGIN_Y = 1.6;

const LIGHT_DIR = normalize3(1, 2, 1);
function normalize3(x: number, y: number, z: number): [number, number, number] {
  const len = Math.hypot(x, y, z) || 1;
  return [x / len, y / len, z / len];
}

const FLOOR_COLOR: [number, number, number] = [0.227, 0.227, 0.29];
const CUBE_COLOR: [number, number, number] = [0.463, 0.725, 0]; // NVIDIA green
const PILLAR_COLOR: [number, number, number] = [0.8, 0.8, 0.8];
const TORUS_COLOR: [number, number, number] = [0.239, 0.545, 0.992];
const SPHERE_COLOR: [number, number, number] = [1.0, 0.42, 0.208];

/**
 * Owns one program + one VAO per mesh for the mock scene's lifetime, and draws it into whatever
 * view/projection is handed to {@link renderEye}. Torus tracks the left controller, sphere the
 * right; each hides when its target is `null` (see {@link MockCloudXR.trackControllers}).
 */
export class WebGLMockScene {
  private readonly program: WebGLProgram;
  private readonly meshes: {
    plane: GLMesh;
    box: GLMesh;
    cylinder: GLMesh;
    torus: GLMesh;
    sphere: GLMesh;
  };
  private readonly uModel: WebGLUniformLocation | null;
  private readonly uView: WebGLUniformLocation | null;
  private readonly uProjection: WebGLUniformLocation | null;
  private readonly uColor: WebGLUniformLocation | null;
  private readonly uLightDir: WebGLUniformLocation | null;

  private sceneTime = 0;
  private torusTarget: [number, number, number] | null = null;
  private sphereTarget: [number, number, number] | null = null;

  constructor(private readonly gl: WebGL2RenderingContext) {
    this.program = createProgram(gl);
    this.meshes = {
      plane: uploadMesh(gl, this.program, buildPlane(10)),
      box: uploadMesh(gl, this.program, buildBox(0.15, 0.15, 0.15)),
      cylinder: uploadMesh(gl, this.program, buildCylinder(0.08, 0.8)),
      torus: uploadMesh(gl, this.program, buildTorus(0.2, 0.06)),
      sphere: uploadMesh(gl, this.program, buildSphere(0.15)),
    };
    this.uModel = gl.getUniformLocation(this.program, 'uModel');
    this.uView = gl.getUniformLocation(this.program, 'uView');
    this.uProjection = gl.getUniformLocation(this.program, 'uProjection');
    this.uColor = gl.getUniformLocation(this.program, 'uColor');
    this.uLightDir = gl.getUniformLocation(this.program, 'uLightDir');
  }

  setSceneTime(seconds: number): void {
    this.sceneTime = seconds;
  }

  setTorusTarget(pos: { x: number; y: number; z: number } | null): void {
    this.torusTarget = pos ? [pos.x, pos.y, pos.z] : null;
  }

  setSphereTarget(pos: { x: number; y: number; z: number } | null): void {
    this.sphereTarget = pos ? [pos.x, pos.y, pos.z] : null;
  }

  /** Draws every object for one eye. `view` must already be an inverted (world-to-camera) matrix. */
  renderEye(view: Mat4, projection: Mat4): void {
    const gl = this.gl;
    gl.enable(gl.DEPTH_TEST);
    gl.depthFunc(gl.LEQUAL);
    gl.depthMask(true);
    gl.disable(gl.CULL_FACE);
    gl.useProgram(this.program);
    gl.uniformMatrix4fv(this.uView, false, view);
    gl.uniformMatrix4fv(this.uProjection, false, projection);
    gl.uniform3f(this.uLightDir, LIGHT_DIR[0], LIGHT_DIR[1], LIGHT_DIR[2]);

    this.draw(this.meshes.plane, mat4Identity(), FLOOR_COLOR);
    this.draw(
      this.meshes.box,
      mat4Multiply(
        mat4Translation(0, SCENE_ORIGIN_Y, -1.5),
        mat4Multiply(mat4RotationY(this.sceneTime), mat4RotationX(this.sceneTime * 0.4))
      ),
      CUBE_COLOR
    );
    this.draw(this.meshes.cylinder, mat4Translation(0.6, SCENE_ORIGIN_Y - 0.6, -1.6), PILLAR_COLOR);

    if (this.torusTarget) {
      const [x, y, z] = this.torusTarget;
      this.draw(
        this.meshes.torus,
        mat4Multiply(mat4Translation(x, y, z), mat4RotationZ(this.sceneTime * 0.6)),
        TORUS_COLOR
      );
    }
    if (this.sphereTarget) {
      const [x, y, z] = this.sphereTarget;
      this.draw(this.meshes.sphere, mat4Translation(x, y, z), SPHERE_COLOR);
    }
  }

  private draw(mesh: GLMesh, model: Mat4, color: [number, number, number]): void {
    const gl = this.gl;
    gl.uniformMatrix4fv(this.uModel, false, model);
    gl.uniform3f(this.uColor, color[0], color[1], color[2]);
    gl.bindVertexArray(mesh.vao);
    gl.drawElements(gl.TRIANGLES, mesh.indexCount, gl.UNSIGNED_SHORT, 0);
  }
}

export { mat4InvertRigid };
