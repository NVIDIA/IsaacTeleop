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
 * XR Input Recorder / Replayer
 *
 * Monkey-patches XRFrame.prototype.getPose and XRFrame.prototype.getJointPose
 * to intercept controller and hand-tracking poses during replay.
 * Gamepad button/axis state is captured per-frame and replayed via a proxy.
 *
 * Frame boundaries are driven explicitly via beginFrame() called from the
 * main requestAnimationFrame loop — this avoids relying on XRFrame object
 * identity, which Chrome on Quest may reuse across callbacks (object pooling).
 */

// ---- serialization types ---------------------------------------------------

export type SerializedPose = {
  px: number;
  py: number;
  pz: number;
  ox: number;
  oy: number;
  oz: number;
  ow: number;
} | null;

export type SerializedJoint = {
  px: number;
  py: number;
  pz: number;
  ox: number;
  oy: number;
  oz: number;
  ow: number;
  radius: number;
} | null;

type SerializedGamepad = {
  buttons: Array<{ value: number; pressed: boolean; touched: boolean }>;
  axes: number[];
};

export type RecordedFrame = {
  poses: {
    leftGrip: SerializedPose;
    leftAim: SerializedPose;
    rightGrip: SerializedPose;
    rightAim: SerializedPose;
  };
  gamepads: {
    left: SerializedGamepad | null;
    right: SerializedGamepad | null;
  };
  // Optional: absent in recordings made before hand-tracking support was added
  handJoints?: {
    left: (SerializedJoint | null)[];
    right: (SerializedJoint | null)[];
  };
};

export type Recording = {
  version: 1;
  frames: RecordedFrame[];
};

// ---- helpers ---------------------------------------------------------------

function serializePose(pose: XRPose | undefined): SerializedPose {
  if (!pose) return null;
  const { position: p, orientation: o } = pose.transform;
  return { px: p.x, py: p.y, pz: p.z, ox: o.x, oy: o.y, oz: o.z, ow: o.w };
}

function serializeGamepad(
  gp: Gamepad | null | undefined,
): SerializedGamepad | null {
  if (!gp) return null;
  return {
    buttons: Array.from(gp.buttons).map((b) => ({
      value: b.value,
      pressed: b.pressed,
      touched: b.touched,
    })),
    axes: Array.from(gp.axes),
  };
}

function makeFakePose(sp: SerializedPose): XRPose | undefined {
  if (!sp) return undefined;
  const transform = new XRRigidTransform(
    { x: sp.px, y: sp.py, z: sp.pz, w: 1 },
    { x: sp.ox, y: sp.oy, z: sp.oz, w: sp.ow },
  );
  return {
    transform,
    emulatedPosition: true,
    linearVelocity: null as unknown as DOMPointReadOnly,
    angularVelocity: null as unknown as DOMPointReadOnly,
  } as unknown as XRPose;
}

function makeFakeJointPose(sj: SerializedJoint): XRJointPose | undefined {
  if (!sj) return undefined;
  const transform = new XRRigidTransform(
    { x: sj.px, y: sj.py, z: sj.pz, w: 1 },
    { x: sj.ox, y: sj.oy, z: sj.oz, w: sj.ow },
  );
  return {
    transform,
    emulatedPosition: true,
    linearVelocity: null as unknown as DOMPointReadOnly,
    angularVelocity: null as unknown as DOMPointReadOnly,
    radius: sj.radius,
  } as unknown as XRJointPose;
}

function makeFakeGamepad(sg: SerializedGamepad): Gamepad {
  return {
    buttons: sg.buttons.map((b) => ({
      value: b.value,
      pressed: b.pressed,
      touched: b.touched,
    })),
    axes: sg.axes,
    id: "recorded",
    index: -1,
    connected: true,
    timestamp: 0,
    mapping: "xr-standard" as GamepadMappingType,
    hapticActuators: [],
    vibrationActuator: null,
  } as unknown as Gamepad;
}

function proxyInputSource(
  src: XRInputSource,
  fakeGamepad: Gamepad,
): XRInputSource {
  return new Proxy(src, {
    get(target, prop) {
      if (prop === "gamepad") return fakeGamepad;
      const val = Reflect.get(target, prop, target);
      return typeof val === "function" ? val.bind(target) : val;
    },
  });
}

function emptyFrame(): RecordedFrame {
  return {
    poses: { leftGrip: null, leftAim: null, rightGrip: null, rightAim: null },
    gamepads: { left: null, right: null },
  };
}

// ---- XRInputRecorder -------------------------------------------------------

export class XRInputRecorder {
  private _mode: "idle" | "recording" | "replaying" = "idle";
  private _frames: RecordedFrame[] = [];
  private _replayFrames: RecordedFrame[] = [];
  private _replayIndex = 0;
  private _loopReplay = true;

  private _currentEntry: RecordedFrame | null = null;
  private _currentReplay: RecordedFrame = emptyFrame();

  private _jointSpaceMap = new WeakMap<
    XRJointSpace,
    { hand: "left" | "right"; index: number }
  >();

  private _origGetPose: typeof XRFrame.prototype.getPose | null = null;
  private _origGetJointPose: typeof XRFrame.prototype.getJointPose | null =
    null;
  private _origInputSourcesDesc: PropertyDescriptor | null = null;
  /** Scene reference space used to proactively capture grip/joint poses for the trace. */
  private _sceneRefSpace: XRSpace | null = null;

  setSceneRefSpace(rs: XRSpace | null): void {
    this._sceneRefSpace = rs;
  }

  get mode() {
    return this._mode;
  }
  get recordedFrameCount() {
    return this._frames.length;
  }
  get replayFrameIndex() {
    return this._replayIndex;
  }

  // ---- lifecycle -----------------------------------------------------------

  startRecording(): void {
    if (this._mode !== "idle")
      throw new Error("XRInputRecorder: already active");
    this._frames = [];
    this._currentEntry = null;
    this._installPatches();
    this._mode = "recording";
  }

  stopRecording(): void {
    if (this._mode !== "recording") return;
    this._removePatches();
    this._currentEntry = null;
    this._mode = "idle";
  }

  startReplay(recording: Recording, loop = true): void {
    if (this._mode !== "idle")
      throw new Error("XRInputRecorder: already active");
    this._replayFrames = recording.frames;
    this._replayIndex = 0;
    this._loopReplay = loop;
    this._currentReplay = emptyFrame();
    this._installPatches();
    this._mode = "replaying";
  }

  stopReplay(): void {
    if (this._mode !== "replaying") return;
    this._removePatches();
    this._mode = "idle";
  }

  /**
   * Must be called once at the start of every requestAnimationFrame callback.
   * connected=true gates replay frame advancement so frames are not consumed
   * while the CloudXR session is still initialising.
   */
  beginFrame(frame: XRFrame, connected = true): void {
    if (this._mode === "recording") {
      const entry = emptyFrame();
      for (const src of frame.session.inputSources) {
        const gp = serializeGamepad(src.gamepad);
        if (src.handedness === "left") entry.gamepads.left = gp;
        else if (src.handedness === "right") entry.gamepads.right = gp;
      }

      // Proactively capture grip/aim poses and hand joints in scene space so
      // the trace works even if CloudXR never calls getPose(gripSpace, ...).
      // These run through the original (unpatched) getPose, then _onGetPose
      // will not overwrite them (null-check guard) if CloudXR uses a different
      // reference space.
      const rs = this._sceneRefSpace;
      const origGet = this._origGetPose;
      const origGetJoint = this._origGetJointPose;
      if (rs && origGet) {
        for (const src of frame.session.inputSources) {
          const h = src.handedness;
          if (h !== "left" && h !== "right") continue;
          if (src.gripSpace) {
            const p = origGet.call(frame, src.gripSpace, rs);
            if (h === "left") entry.poses.leftGrip = serializePose(p);
            else entry.poses.rightGrip = serializePose(p);
          }
          if (src.targetRaySpace) {
            const p = origGet.call(frame, src.targetRaySpace, rs);
            if (h === "left") entry.poses.leftAim = serializePose(p);
            else entry.poses.rightAim = serializePose(p);
          }
          if (src.hand && origGetJoint) {
            this._ensureJointMap(frame.session);
            if (!entry.handJoints) entry.handJoints = { left: [], right: [] };
            let i = 0;
            for (const [, joint] of src.hand.entries()) {
              const jp = origGetJoint.call(frame, joint, rs);
              entry.handJoints[h][i] = jp
                ? {
                    px: jp.transform.position.x,
                    py: jp.transform.position.y,
                    pz: jp.transform.position.z,
                    ox: jp.transform.orientation.x,
                    oy: jp.transform.orientation.y,
                    oz: jp.transform.orientation.z,
                    ow: jp.transform.orientation.w,
                    radius: jp.radius ?? 0.005,
                  }
                : null;
              i++;
            }
          }
        }
      }

      this._currentEntry = entry;
      this._frames.push(entry);
    } else if (this._mode === "replaying" && connected) {
      this._currentReplay =
        this._replayFrames[this._replayIndex] ?? emptyFrame();
      this._replayIndex++;
      if (this._replayIndex >= this._replayFrames.length) {
        this._replayIndex = this._loopReplay
          ? 0
          : this._replayFrames.length - 1;
      }
    }
  }

  /** The frame data for the current tick: recording entry when recording, replay frame when replaying. */
  get currentFrame(): RecordedFrame | null {
    if (this._mode === "recording") return this._currentEntry;
    if (this._mode === "replaying") return this._currentReplay;
    return null;
  }

  // ---- serialization -------------------------------------------------------

  exportJSON(): string {
    return JSON.stringify({
      version: 1,
      frames: this._frames,
    } satisfies Recording);
  }

  static importJSON(json: string): Recording {
    const r = JSON.parse(json) as Recording;
    if (r.version !== 1)
      throw new Error(`Unsupported recording version: ${r.version}`);
    return r;
  }

  getRecording(): Recording {
    return { version: 1, frames: [...this._frames] };
  }

  // ---- patch install / remove ----------------------------------------------

  private _installPatches(): void {
    const self = this;

    this._origGetPose = XRFrame.prototype.getPose;
    XRFrame.prototype.getPose = function (
      this: XRFrame,
      space: XRSpace,
      baseSpace: XRSpace,
    ): XRPose | undefined {
      return self._onGetPose(this, space, baseSpace);
    };

    this._origGetJointPose = XRFrame.prototype.getJointPose;
    XRFrame.prototype.getJointPose = function (
      this: XRFrame,
      joint: XRJointSpace,
      baseSpace: XRSpace,
    ): XRJointPose | undefined {
      return self._onGetJointPose(this, joint, baseSpace);
    };

    // Intercept XRSession.inputSources so gamepad state is proxied during replay
    // even when the CloudXR SDK reads it via xrFrame.session.inputSources directly.
    const inputSourcesDesc = Object.getOwnPropertyDescriptor(
      XRSession.prototype,
      "inputSources",
    );
    if (inputSourcesDesc?.get) {
      this._origInputSourcesDesc = inputSourcesDesc;
      const origGet = inputSourcesDesc.get;
      Object.defineProperty(XRSession.prototype, "inputSources", {
        get(this: XRSession) {
          const real = origGet.call(this);
          if (self._mode !== "replaying") return real;
          const rframe = self._currentReplay;
          return Array.from(real as XRInputSourceArray).map(
            (src: XRInputSource) => {
              const sg =
                src.handedness === "left"
                  ? rframe.gamepads.left
                  : src.handedness === "right"
                    ? rframe.gamepads.right
                    : null;
              return sg ? proxyInputSource(src, makeFakeGamepad(sg)) : src;
            },
          );
        },
        configurable: true,
      });
    }
  }

  private _removePatches(): void {
    if (this._origGetPose) {
      XRFrame.prototype.getPose = this._origGetPose;
      this._origGetPose = null;
    }
    if (this._origGetJointPose) {
      XRFrame.prototype.getJointPose = this._origGetJointPose;
      this._origGetJointPose = null;
    }
    if (this._origInputSourcesDesc) {
      Object.defineProperty(
        XRSession.prototype,
        "inputSources",
        this._origInputSourcesDesc,
      );
      this._origInputSourcesDesc = null;
    }
  }

  // ---- getPose handler -----------------------------------------------------

  private _onGetPose(
    frame: XRFrame,
    space: XRSpace,
    baseSpace: XRSpace,
  ): XRPose | undefined {
    if (this._mode === "recording") {
      const real = this._origGetPose!.call(frame, space, baseSpace);
      const entry = this._currentEntry;
      if (entry) {
        for (const src of frame.session.inputSources) {
          if (space === src.gripSpace) {
            // Only write if not already set by proactive scene-space capture in beginFrame.
            if (src.handedness === "left" && entry.poses.leftGrip === null)
              entry.poses.leftGrip = serializePose(real);
            else if (
              src.handedness === "right" &&
              entry.poses.rightGrip === null
            )
              entry.poses.rightGrip = serializePose(real);
            break;
          }
          if (space === src.targetRaySpace) {
            if (src.handedness === "left" && entry.poses.leftAim === null)
              entry.poses.leftAim = serializePose(real);
            else if (
              src.handedness === "right" &&
              entry.poses.rightAim === null
            )
              entry.poses.rightAim = serializePose(real);
            break;
          }
        }
      }
      return real;
    }

    if (this._mode === "replaying") {
      for (const src of frame.session.inputSources) {
        if (space === src.gripSpace) {
          const rframe = this._currentReplay;
          if (src.handedness === "left")
            return makeFakePose(rframe.poses.leftGrip);
          if (src.handedness === "right")
            return makeFakePose(rframe.poses.rightGrip);
        }
      }
      return this._origGetPose!.call(frame, space, baseSpace);
    }

    return this._origGetPose!.call(frame, space, baseSpace);
  }

  // ---- getJointPose handler ------------------------------------------------

  private _onGetJointPose(
    frame: XRFrame,
    joint: XRJointSpace,
    baseSpace: XRSpace,
  ): XRJointPose | undefined {
    if (this._mode === "recording") {
      this._ensureJointMap(frame.session);
      const real = this._origGetJointPose!.call(frame, joint, baseSpace);
      const info = this._jointSpaceMap.get(joint);
      const entry = this._currentEntry;
      if (info && entry) {
        if (!entry.handJoints) entry.handJoints = { left: [], right: [] };
        entry.handJoints[info.hand][info.index] = real
          ? {
              px: real.transform.position.x,
              py: real.transform.position.y,
              pz: real.transform.position.z,
              ox: real.transform.orientation.x,
              oy: real.transform.orientation.y,
              oz: real.transform.orientation.z,
              ow: real.transform.orientation.w,
              radius: real.radius ?? 0.005,
            }
          : null;
      }
      return real;
    }

    if (this._mode === "replaying") {
      const rframe = this._currentReplay;
      if (!rframe.handJoints)
        return this._origGetJointPose!.call(frame, joint, baseSpace);
      this._ensureJointMap(frame.session);
      const info = this._jointSpaceMap.get(joint);
      if (info)
        return makeFakeJointPose(
          rframe.handJoints[info.hand][info.index] ?? null,
        );
      return this._origGetJointPose!.call(frame, joint, baseSpace);
    }

    return this._origGetJointPose!.call(frame, joint, baseSpace);
  }

  // ---- joint map builder ---------------------------------------------------

  private _ensureJointMap(session: XRSession): void {
    for (const src of session.inputSources) {
      if (!src.hand) continue;
      const hand = src.handedness;
      if (hand !== "left" && hand !== "right") continue;
      let index = 0;
      for (const [, jointSpace] of src.hand.entries()) {
        if (!this._jointSpaceMap.has(jointSpace)) {
          this._jointSpaceMap.set(jointSpace, { hand, index });
        }
        index++;
      }
    }
  }
}
