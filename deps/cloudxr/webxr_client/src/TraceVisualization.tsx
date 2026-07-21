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
 * TraceVisualization.tsx - R3F component that renders hand/controller path traces.
 *
 * Renders rolling-window point-cloud traces for left and right grip/wrist positions.
 * No meshes — the existing IsaacTeleop hand/controller models already show current pose.
 *
 * In idle mode (not recording/replaying) poses are queried directly from the live
 * XR session in the scene's reference space so traces build up at all times.
 * During recording/replay, poses come from the recorder's current frame.
 *
 * All geometry is pre-allocated and mutated directly; positions/visibility are
 * never driven by React state so this runs at full XR frame rate.
 */

import { useFrame } from "@react-three/fiber";
import { useRef, useEffect } from "react";
import {
  BufferAttribute,
  BufferGeometry,
  Color,
  Points,
  PointsMaterial,
} from "three";

import type {
  XRInputRecorder,
  RecordedFrame,
  SerializedJoint,
} from "./xrInputRecorder";

// ---- constants -------------------------------------------------------------


const TRACE_LEN = 500;
// Fixed screen-space pixel size — reliable in WebXR stereo
const TRACE_DOT_SIZE = 6;

// ---- TraceBuffer -----------------------------------------------------------

class TraceBuffer {
  private readonly buf: Float32Array;
  private writeIdx = 0;
  private count = 0;

  constructor(private readonly capacity: number) {
    this.buf = new Float32Array(capacity * 3);
  }

  push(x: number, y: number, z: number): void {
    const i = this.writeIdx * 3;
    this.buf[i] = x;
    this.buf[i + 1] = y;
    this.buf[i + 2] = z;
    this.writeIdx = (this.writeIdx + 1) % this.capacity;
    if (this.count < this.capacity) this.count++;
  }

  /**
   * Fill positions/colors oldest→newest with brightness ramping 0.1→1.0.
   * Returns the number of valid points written.
   */
  fill(
    positions: Float32Array,
    colors: Float32Array,
    br: number,
    bg: number,
    bb: number,
  ): number {
    if (this.count === 0) return 0;
    const start = this.count < this.capacity ? 0 : this.writeIdx;
    const last = this.count - 1;
    for (let i = 0; i < this.count; i++) {
      const src = ((start + i) % this.capacity) * 3;
      const dst = i * 3;
      positions[dst] = this.buf[src];
      positions[dst + 1] = this.buf[src + 1];
      positions[dst + 2] = this.buf[src + 2];
      const t = last > 0 ? i / last : 1;
      const brightness = 0.1 + 0.9 * t;
      colors[dst] = br * brightness;
      colors[dst + 1] = bg * brightness;
      colors[dst + 2] = bb * brightness;
    }
    return this.count;
  }

  clear(): void {
    this.writeIdx = 0;
    this.count = 0;
  }
}

// ---- helpers ---------------------------------------------------------------

interface TraceChannel {
  buf: TraceBuffer;
  points: Points;
  positions: Float32Array;
  colors: Float32Array;
  br: number;
  bg: number;
  bb: number;
}

function makeTraceChannel(color: string): TraceChannel {
  const positions = new Float32Array(TRACE_LEN * 3);
  const colors = new Float32Array(TRACE_LEN * 3);
  const geo = new BufferGeometry();
  geo.setAttribute("position", new BufferAttribute(positions, 3));
  geo.setAttribute("color", new BufferAttribute(colors, 3));
  geo.setDrawRange(0, 0);
  const mat = new PointsMaterial({
    vertexColors: true,
    size: TRACE_DOT_SIZE,
    sizeAttenuation: false,
  });
  const points = new Points(geo, mat);
  points.visible = false;
  const c = new Color(color);
  return {
    buf: new TraceBuffer(TRACE_LEN),
    points,
    positions,
    colors,
    br: c.r,
    bg: c.g,
    bb: c.b,
  };
}

type PoseLike = { px: number; py: number; pz: number } | null | undefined;
type JointLike = (PoseLike & { radius?: number }) | null | undefined;

// ---- component -------------------------------------------------------------

interface TraceVisualizationProps {
  recorder: XRInputRecorder;
  showTrace: boolean;
}

export function TraceVisualization({
  recorder,
  showTrace,
}: TraceVisualizationProps) {
  // Stable trace channels initialised on first render
  const traceRef = useRef<{
    leftGrip: TraceChannel;
    rightGrip: TraceChannel;
    leftWrist: TraceChannel;
    rightWrist: TraceChannel;
  } | null>(null);

  if (traceRef.current === null) {
    traceRef.current = {
      leftGrip: makeTraceChannel("#4488ff"),
      rightGrip: makeTraceChannel("#44ff88"),
      leftWrist: makeTraceChannel("#ff4422"),
      rightWrist: makeTraceChannel("#ff44cc"),
    };
  }
  const traceChannels = Object.values(traceRef.current);

  // Clear accumulated dots whenever the recorder mode changes so traces from a
  // prior recording don't ghost under the next live trace or replay.
  useEffect(() => {
    traceRef.current && Object.values(traceRef.current).forEach(ch => ch.buf.clear());
  }, [recorder.mode]);

  useFrame((state) => {
    const t = traceRef.current!;

    // Use recorded/replayed frame when active, otherwise query live XR poses
    let frame: RecordedFrame | null = recorder.currentFrame;

    if (!frame) {
      const xrFrame = state.gl.xr.getFrame() as XRFrame | null;
      const refSpace =
        state.gl.xr.getReferenceSpace() as XRReferenceSpace | null;
      if (xrFrame && refSpace) {
        const livePoses: RecordedFrame["poses"] = {
          leftGrip: null,
          leftAim: null,
          rightGrip: null,
          rightAim: null,
        };
        const liveJoints: {
          left: (SerializedJoint | null)[];
          right: (SerializedJoint | null)[];
        } = { left: [], right: [] };
        let hasJoints = false;

        for (const src of xrFrame.session.inputSources) {
          const h = src.handedness;
          if (h !== "left" && h !== "right") continue;
          if (src.gripSpace) {
            const p = xrFrame.getPose(src.gripSpace, refSpace);
            if (p) {
              const { position: pos, orientation: ori } = p.transform;
              const sp = {
                px: pos.x,
                py: pos.y,
                pz: pos.z,
                ox: ori.x,
                oy: ori.y,
                oz: ori.z,
                ow: ori.w,
              };
              if (h === "left") livePoses.leftGrip = sp;
              else livePoses.rightGrip = sp;
            }
          }
          if (src.hand) {
            hasJoints = true;
            let i = 0;
            for (const [, joint] of src.hand.entries()) {
              const jp = xrFrame.getJointPose?.(joint, refSpace);
              if (jp) {
                const { position: pos, orientation: ori } = jp.transform;
                liveJoints[h][i] = {
                  px: pos.x,
                  py: pos.y,
                  pz: pos.z,
                  ox: ori.x,
                  oy: ori.y,
                  oz: ori.z,
                  ow: ori.w,
                  radius: jp.radius ?? 0.005,
                };
              } else {
                liveJoints[h][i] = null;
              }
              i++;
            }
          }
        }

        frame = {
          poses: livePoses,
          gamepads: { left: null, right: null },
          handJoints: hasJoints ? liveJoints : undefined,
        };
      }
    }

    const updateTrace = (slot: TraceChannel, pose: PoseLike) => {
      if (!showTrace) {
        slot.points.visible = false;
        return;
      }
      if (frame && pose) {
        slot.buf.push(pose.px, pose.py, pose.pz);
        const count = slot.buf.fill(
          slot.positions,
          slot.colors,
          slot.br,
          slot.bg,
          slot.bb,
        );
        const geo = slot.points.geometry as BufferGeometry;
        geo.setDrawRange(0, count);
        (geo.attributes.position as BufferAttribute).needsUpdate = true;
        (geo.attributes.color as BufferAttribute).needsUpdate = true;
        slot.points.visible = true;
      }
      // showTrace && tracking loss: leave visible so accumulated history stays rendered
    };

    updateTrace(t.leftGrip, frame?.poses.leftGrip);
    updateTrace(t.rightGrip, frame?.poses.rightGrip);
    updateTrace(t.leftWrist, frame?.handJoints?.left?.[0] as JointLike);
    updateTrace(t.rightWrist, frame?.handJoints?.right?.[0] as JointLike);
  });

  return (
    <>
      {traceChannels.map((ch, i) => (
        <primitive key={i} object={ch.points} />
      ))}
    </>
  );
}
