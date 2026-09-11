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
 * Records controller and hand input in one canonical, R3F scene-space frame.
 * During replay, adaptTrackingFrame() exposes the recorded input only to the
 * CloudXR tracking call. The browser's real XRFrame remains untouched for R3F,
 * UI pointers, and CloudXR rendering/reprojection.
 */

import { XRReplaySession } from './xrReplaySession';

type PoseData = {
  px: number;
  py: number;
  pz: number;
  ox: number;
  oy: number;
  oz: number;
  ow: number;
};

export type SerializedPose = PoseData | null;
export type SerializedJoint = (PoseData & { radius: number }) | null;

type SerializedGamepad = {
  buttons: Array<{ value: number; pressed: boolean; touched: boolean }>;
  axes: number[];
};

type Hands<T> = { left: T; right: T };
type JointPoses = Record<string, SerializedJoint>;

export type RecordedFrame = {
  /** Milliseconds since the first recorded XR frame. */
  timeMs: number;
  /** Grip and target-ray poses relative to R3F's scene reference space. */
  poses: {
    leftGrip: SerializedPose;
    leftAim: SerializedPose;
    rightGrip: SerializedPose;
    rightAim: SerializedPose;
  };
  gamepads: Hands<SerializedGamepad | null>;
  /** Joint poses keyed by XRHandJoint name, also in scene space. */
  handJoints: Hands<JointPoses>;
};

export type Recording = {
  version: 1;
  recordedAt?: number;
  /** Optional cross-session origin calibration. Absent in legacy recordings. */
  calibration?: {
    mode: 'viewer-start-yaw';
    /** Gravity-aligned viewer pose in the recording's scene reference space. */
    pose: PoseData;
  };
  frames: RecordedFrame[];
};

export type ReplayPacing = 'frame' | 'time';

const IDENTITY_POSE: PoseData = { px: 0, py: 0, pz: 0, ox: 0, oy: 0, oz: 0, ow: 1 };

function emptyFrame(timeMs = 0): RecordedFrame {
  return {
    timeMs,
    poses: { leftGrip: null, leftAim: null, rightGrip: null, rightAim: null },
    gamepads: { left: null, right: null },
    handJoints: { left: {}, right: {} },
  };
}

function serializePose(pose: XRPose | null | undefined): SerializedPose {
  if (!pose) return null;
  return serializeTransform(pose.transform);
}

function serializeTransform(transform: XRRigidTransform): PoseData {
  const { position: p, orientation: o } = transform;
  return { px: p.x, py: p.y, pz: p.z, ox: o.x, oy: o.y, oz: o.z, ow: o.w };
}

function isPoseData(value: unknown): value is PoseData {
  if (typeof value !== 'object' || value === null) return false;
  const pose = value as Partial<PoseData>;
  return [pose.px, pose.py, pose.pz, pose.ox, pose.oy, pose.oz, pose.ow].every(component =>
    Number.isFinite(component)
  );
}

function serializeJoint(pose: XRJointPose | null | undefined): SerializedJoint {
  const serialized = serializePose(pose);
  return serialized ? { ...serialized, radius: pose?.radius ?? 0.005 } : null;
}

function serializeGamepad(gamepad: Gamepad | null | undefined): SerializedGamepad | null {
  if (!gamepad) return null;
  return {
    buttons: Array.from(gamepad.buttons, ({ value, pressed, touched }) => ({
      value,
      pressed,
      touched,
    })),
    axes: Array.from(gamepad.axes),
  };
}

function captureFrame(frame: XRFrame, referenceSpace: XRReferenceSpace, timeMs = 0): RecordedFrame {
  const captured = emptyFrame(timeMs);

  for (const source of frame.session.inputSources) {
    const hand = source.handedness;
    if (hand !== 'left' && hand !== 'right') continue;

    captured.gamepads[hand] = serializeGamepad(source.gamepad);
    captured.poses[`${hand}Grip`] = source.gripSpace
      ? serializePose(frame.getPose(source.gripSpace, referenceSpace))
      : null;
    captured.poses[`${hand}Aim`] = source.targetRaySpace
      ? serializePose(frame.getPose(source.targetRaySpace, referenceSpace))
      : null;

    if (source.hand && frame.getJointPose) {
      for (const [name, joint] of source.hand.entries()) {
        captured.handJoints[hand][name] = serializeJoint(frame.getJointPose(joint, referenceSpace));
      }
    }
  }

  return captured;
}

function makePose(pose: PoseData): XRPose {
  // WebXR permits null velocities; @types/webxr currently excludes null.
  return {
    transform: new XRRigidTransform(
      { x: pose.px, y: pose.py, z: pose.pz, w: 1 },
      { x: pose.ox, y: pose.oy, z: pose.oz, w: pose.ow }
    ),
    emulatedPosition: true,
    linearVelocity: null,
    angularVelocity: null,
  } as unknown as XRPose;
}

function makeJointPose(joint: Exclude<SerializedJoint, null>): XRJointPose {
  return { ...makePose(joint), radius: joint.radius } as XRJointPose;
}

function makeGamepad(gamepad: SerializedGamepad): Gamepad {
  return {
    buttons: gamepad.buttons.map(({ value, pressed, touched }) => ({
      value,
      pressed,
      touched,
    })),
    axes: gamepad.axes,
    id: 'recorded',
    index: -1,
    connected: true,
    timestamp: 0,
    mapping: 'xr-standard',
    hapticActuators: [],
    vibrationActuator: null,
  } as unknown as Gamepad;
}

function bindWebXRMember(target: object, property: PropertyKey): unknown {
  const value = Reflect.get(target, property, target);
  return typeof value === 'function' ? value.bind(target) : value;
}

function lerp(from: number, to: number, alpha: number): number {
  return from + (to - from) * alpha;
}

function interpolatePose<T extends PoseData>(from: T, to: T, alpha: number): T {
  let tox = to.ox;
  let toy = to.oy;
  let toz = to.oz;
  let tow = to.ow;
  const dot = from.ox * tox + from.oy * toy + from.oz * toz + from.ow * tow;
  if (dot < 0) {
    tox = -tox;
    toy = -toy;
    toz = -toz;
    tow = -tow;
  }

  const shortestDot = Math.abs(dot);
  let fromScale = 1 - alpha;
  let toScale = alpha;
  if (shortestDot < 0.9995) {
    const angle = Math.acos(Math.min(1, shortestDot));
    const sinAngle = Math.sin(angle);
    fromScale = Math.sin((1 - alpha) * angle) / sinAngle;
    toScale = Math.sin(alpha * angle) / sinAngle;
  }

  let ox = from.ox * fromScale + tox * toScale;
  let oy = from.oy * fromScale + toy * toScale;
  let oz = from.oz * fromScale + toz * toScale;
  let ow = from.ow * fromScale + tow * toScale;
  const magnitude = Math.hypot(ox, oy, oz, ow);
  if (magnitude > 0) {
    ox /= magnitude;
    oy /= magnitude;
    oz /= magnitude;
    ow /= magnitude;
  }

  return {
    ...from,
    px: lerp(from.px, to.px, alpha),
    py: lerp(from.py, to.py, alpha),
    pz: lerp(from.pz, to.pz, alpha),
    ox,
    oy,
    oz,
    ow,
  };
}

function interpolateOptionalPose<T extends PoseData>(
  from: T | null | undefined,
  to: T | null | undefined,
  alpha: number
): T | null {
  // Tracking presence is discrete. Do not invent a pose before it appears or
  // keep one after the timestamp at which it disappears.
  if (!from || !to) return from ?? null;
  return interpolatePose(from, to, alpha);
}

function interpolateGamepad(
  from: SerializedGamepad | null,
  to: SerializedGamepad | null,
  alpha: number
): SerializedGamepad | null {
  if (!from || !to) return from;
  // A layout change means the input source changed. Keep the complete earlier
  // sample until the next timestamp instead of partially mixing two devices.
  if (from.axes.length !== to.axes.length || from.buttons.length !== to.buttons.length) {
    return from;
  }
  return {
    axes: from.axes.map((value, index) => lerp(value, to.axes[index], alpha)),
    buttons: from.buttons.map((button, index) => {
      const next = to.buttons[index];
      return {
        value: lerp(button.value, next.value, alpha),
        pressed: button.pressed,
        touched: button.touched,
      };
    }),
  };
}

function interpolateJoints(from: JointPoses, to: JointPoses, alpha: number): JointPoses {
  const result: JointPoses = {};
  for (const name of new Set([...Object.keys(from), ...Object.keys(to)])) {
    const fromJoint = from[name];
    const toJoint = to[name];
    if (!fromJoint || !toJoint) {
      result[name] = fromJoint ?? null;
      continue;
    }
    result[name] = {
      ...interpolatePose(fromJoint, toJoint, alpha),
      radius: lerp(fromJoint.radius, toJoint.radius, alpha),
    };
  }
  return result;
}

function interpolateFrame(from: RecordedFrame, to: RecordedFrame, timeMs: number): RecordedFrame {
  const interval = to.timeMs - from.timeMs;
  const alpha = interval > 0 ? (timeMs - from.timeMs) / interval : 0;
  return {
    timeMs,
    poses: {
      leftGrip: interpolateOptionalPose(from.poses.leftGrip, to.poses.leftGrip, alpha),
      leftAim: interpolateOptionalPose(from.poses.leftAim, to.poses.leftAim, alpha),
      rightGrip: interpolateOptionalPose(from.poses.rightGrip, to.poses.rightGrip, alpha),
      rightAim: interpolateOptionalPose(from.poses.rightAim, to.poses.rightAim, alpha),
    },
    gamepads: {
      left: interpolateGamepad(from.gamepads.left, to.gamepads.left, alpha),
      right: interpolateGamepad(from.gamepads.right, to.gamepads.right, alpha),
    },
    handJoints: {
      left: interpolateJoints(from.handJoints.left, to.handJoints.left, alpha),
      right: interpolateJoints(from.handJoints.right, to.handJoints.right, alpha),
    },
  };
}

function sampleAtTime(
  frames: RecordedFrame[],
  timeMs: number
): { frame: RecordedFrame; index: number } {
  if (timeMs <= frames[0].timeMs) return { frame: frames[0], index: 0 };

  let low = 0;
  let high = frames.length;
  while (low < high) {
    const middle = Math.floor((low + high) / 2);
    if (frames[middle].timeMs <= timeMs) low = middle + 1;
    else high = middle;
  }

  const index = low - 1;
  if (index >= frames.length - 1 || frames[index].timeMs === timeMs) {
    return { frame: frames[index], index };
  }
  return {
    frame: interpolateFrame(frames[index], frames[index + 1], timeMs),
    index,
  };
}

function replayDuration(frames: RecordedFrame[]): number {
  if (frames.length < 2) return 0;
  const firstTime = frames[0].timeMs;
  const lastTime = frames[frames.length - 1].timeMs;
  for (let index = frames.length - 1; index > 0; index--) {
    const terminalInterval = frames[index].timeMs - frames[index - 1].timeMs;
    if (terminalInterval > 0) return lastTime - firstTime + terminalInterval;
  }
  return 0;
}

/** Apply a baseSpace <- sceneSpace transform to a pose expressed in sceneSpace. */
function transformByPose<T extends PoseData>(pose: T, baseFromScene: PoseData): T {
  const p = { x: baseFromScene.px, y: baseFromScene.py, z: baseFromScene.pz };
  const q = {
    x: baseFromScene.ox,
    y: baseFromScene.oy,
    z: baseFromScene.oz,
    w: baseFromScene.ow,
  };

  // Rotate the recorded translation by q using v' = v + qw*t + cross(q.xyz, t).
  const tx = 2 * (q.y * pose.pz - q.z * pose.py);
  const ty = 2 * (q.z * pose.px - q.x * pose.pz);
  const tz = 2 * (q.x * pose.py - q.y * pose.px);

  return {
    ...pose,
    px: p.x + pose.px + q.w * tx + q.y * tz - q.z * ty,
    py: p.y + pose.py + q.w * ty + q.z * tx - q.x * tz,
    pz: p.z + pose.pz + q.w * tz + q.x * ty - q.y * tx,
    ox: q.w * pose.ox + q.x * pose.ow + q.y * pose.oz - q.z * pose.oy,
    oy: q.w * pose.oy - q.x * pose.oz + q.y * pose.ow + q.z * pose.ox,
    oz: q.w * pose.oz + q.x * pose.oy - q.y * pose.ox + q.z * pose.ow,
    ow: q.w * pose.ow - q.x * pose.ox - q.y * pose.oy - q.z * pose.oz,
  };
}

/** Apply the real baseSpace <- sceneSpace transform to a recorded pose. */
function transformFromScene<T extends PoseData>(pose: T, baseFromScene: XRRigidTransform): T {
  return transformByPose(pose, serializeTransform(baseFromScene));
}

function inversePose(pose: PoseData): PoseData {
  const magnitudeSquared =
    pose.ox * pose.ox + pose.oy * pose.oy + pose.oz * pose.oz + pose.ow * pose.ow;
  const scale = magnitudeSquared > 0 ? 1 / magnitudeSquared : 1;
  const inverseOrientation = {
    ox: -pose.ox * scale,
    oy: -pose.oy * scale,
    oz: -pose.oz * scale,
    ow: pose.ow * scale,
  };
  const inverseTranslation = transformByPose(
    { px: -pose.px, py: -pose.py, pz: -pose.pz, ox: 0, oy: 0, oz: 0, ow: 1 },
    { px: 0, py: 0, pz: 0, ...inverseOrientation }
  );
  return {
    px: inverseTranslation.px,
    py: inverseTranslation.py,
    pz: inverseTranslation.pz,
    ...inverseOrientation,
  };
}

/** Keep translation and heading while removing viewer pitch and roll. */
function gravityAlignedViewerPose(pose: PoseData): PoseData {
  const yaw = Math.atan2(
    2 * (pose.ox * pose.oz + pose.ow * pose.oy),
    1 - 2 * (pose.ox * pose.ox + pose.oy * pose.oy)
  );
  const halfYaw = yaw / 2;
  return {
    px: pose.px,
    py: pose.py,
    pz: pose.pz,
    ox: 0,
    oy: Math.sin(halfYaw),
    oz: 0,
    ow: Math.cos(halfYaw),
  };
}

function captureViewerCalibration(
  frame: XRFrame,
  referenceSpace: XRReferenceSpace
): Recording['calibration'] | undefined {
  const viewerPose = serializePose(frame.getViewerPose(referenceSpace));
  return viewerPose
    ? { mode: 'viewer-start-yaw', pose: gravityAlignedViewerPose(viewerPose) }
    : undefined;
}

function sceneAlignment(recordedViewer: PoseData, currentViewer: PoseData): PoseData {
  // currentScene <- recordedScene = currentScene <- viewer <- recordedScene.
  return transformByPose(inversePose(recordedViewer), currentViewer);
}

/**
 * Monotonic frame clock in ms. Some runtimes (e.g. PICO) leave
 * XRFrame.predictedDisplayTime undefined; without a fallback that yields NaN,
 * which serializes to null and makes recordings fail import validation, and
 * breaks time-paced replay. Fall back to performance.now() so both stay finite.
 */
function frameTimestampMs(frame: XRFrame): number {
  return Number.isFinite(frame.predictedDisplayTime)
    ? frame.predictedDisplayTime
    : performance.now();
}

export class XRInputRecorder {
  private _mode: 'idle' | 'recording' | 'replaying' = 'idle';
  private _frames: RecordedFrame[] = [];
  private _replayFrames: RecordedFrame[] = [];
  private _replayIndex = 0;
  private _loopReplay = true;
  private _replayPacing: ReplayPacing = 'time';
  private _replayElapsedMs = 0;
  private _lastReplayDisplayTime: number | null = null;
  private _currentFrame: RecordedFrame | null = null;
  private _sceneReferenceSpace: XRReferenceSpace | null = null;
  private _recordingStartTime: number | null = null;
  private _recordedAt: number | undefined;
  private _recordingCalibration: Recording['calibration'];
  private _recordingAlignment: PoseData | null = null;
  private _alignmentCache = new WeakMap<Recording, PoseData>();
  private _replayRecording: Recording | null = null;
  private _replaySceneAlignment: PoseData | null = null;
  private _calibrationRequested = false;
  private _observedSession: XRSession | null = null;
  private _observedReferenceSpace: XRReferenceSpace | null = null;
  // Cached alignments use the origin observed at session/reference-space entry.
  private _currentFromInitial: PoseData = IDENTITY_POSE;
  private _recordingInterrupted = false;
  private _trackingSession: XRReplaySession | null = null;
  private _recordedHandSources: XRInputSource[] = [];
  private _sourceProxies = new WeakMap<XRInputSource, XRInputSource>();

  get mode() {
    return this._mode;
  }

  get recordedFrameCount() {
    return this._frames.length;
  }

  get replayFrameIndex() {
    return this._replayIndex;
  }

  get currentFrame(): RecordedFrame | null {
    return this._currentFrame;
  }

  get replayNeedsCalibration(): boolean {
    return (
      this._mode === 'replaying' &&
      !!this._replayRecording?.calibration &&
      !this._alignmentCache.has(this._replayRecording)
    );
  }

  get recordingInterrupted(): boolean {
    return this._recordingInterrupted;
  }

  /** Call after the operator returns to the recording's physical starting pose. */
  calibrateReplay(): void {
    if (this.replayNeedsCalibration && this._observedReferenceSpace) {
      this._calibrationRequested = true;
    }
  }

  startRecording(): void {
    this._assertIdle();
    this._frames = [];
    this._currentFrame = null;
    this._recordingStartTime = null;
    this._recordedAt = Date.now();
    this._recordingCalibration = undefined;
    this._recordingAlignment = null;
    this._recordingInterrupted = false;
    this._mode = 'recording';
  }

  stopRecording(): void {
    if (this._mode !== 'recording') return;
    this._currentFrame = null;
    this._mode = 'idle';
  }

  startReplay(recording: Recording, loop = true, pacing: ReplayPacing = 'time'): void {
    this._assertIdle();
    this._replayFrames = recording.frames;
    this._recordedHandSources = (['left', 'right'] as const).flatMap(handedness => {
      const names = new Set<string>();
      for (const frame of recording.frames) {
        for (const name of Object.keys(frame.handJoints[handedness])) names.add(name);
      }
      if (!names.size) return [];
      const hand = new Map<XRHandJoint, XRJointSpace>();
      for (const name of names) {
        hand.set(
          name as XRHandJoint,
          Object.assign(new EventTarget(), { jointName: name as XRHandJoint })
        );
      }
      return [
        {
          handedness,
          // @types/webxr still requires obsolete numeric constants on XRHand.
          hand: hand as XRHand,
          targetRayMode: 'tracked-pointer' as const,
          targetRaySpace: new EventTarget(),
          gripSpace: new EventTarget(),
          profiles: ['generic-hand-select'],
        },
      ];
    });
    this._replayIndex = 0;
    this._loopReplay = loop;
    this._replayPacing = pacing;
    this._replayElapsedMs = 0;
    this._lastReplayDisplayTime = null;
    this._currentFrame = null;
    this._replayRecording = recording;
    this._replaySceneAlignment = null;
    this._calibrationRequested = false;
    this._mode = 'replaying';
  }

  stopReplay(): void {
    if (this._mode !== 'replaying') return;
    this._currentFrame = null;
    this._lastReplayDisplayTime = null;
    this._replayRecording = null;
    this._recordedHandSources = [];
    this._replaySceneAlignment = null;
    this._calibrationRequested = false;
    this._mode = 'idle';
  }

  /**
   * Drive recording/replay once per XR animation frame. Recording and replay
   * advance only while CloudXR is connected; idle capture is optional and is
   * used by the trace visualization.
   */
  beginFrame(
    frame: XRFrame,
    sceneReferenceSpace: XRReferenceSpace | null,
    connected = true,
    captureLive = false
  ): void {
    this._observeReferenceSpace(frame.session, sceneReferenceSpace);

    if (this._mode === 'idle') {
      this._currentFrame =
        captureLive && sceneReferenceSpace ? captureFrame(frame, sceneReferenceSpace) : null;
      return;
    }

    if (!connected) {
      if (this._mode === 'replaying') this._lastReplayDisplayTime = null;
      return;
    }

    if (this._mode === 'recording') {
      if (!sceneReferenceSpace) return;
      if (!this._recordingCalibration) {
        this._recordingCalibration = captureViewerCalibration(frame, sceneReferenceSpace);
        if (!this._recordingCalibration) return;
        this._recordingAlignment = inversePose(this._currentFromInitial);
      }
      const now = frameTimestampMs(frame);
      this._recordingStartTime ??= now;
      const timeMs = Math.max(0, now - this._recordingStartTime);
      this._currentFrame = captureFrame(frame, sceneReferenceSpace, timeMs);
      this._frames.push(this._currentFrame);
      return;
    }

    if (this._replayFrames.length === 0) {
      this._currentFrame = null;
      return;
    }

    if (!sceneReferenceSpace || !this._prepareReplayAlignment(frame, sceneReferenceSpace)) {
      this._lastReplayDisplayTime = null;
      this._currentFrame = null;
      return;
    }

    if (this._replayPacing === 'time') {
      this._advanceTimedReplay(frameTimestampMs(frame));
      return;
    }

    this._currentFrame = this._replayFrames[this._replayIndex];
    if (this._replayIndex < this._replayFrames.length - 1) {
      this._replayIndex++;
    } else if (this._loopReplay) {
      this._replayIndex = 0;
    }
  }

  private _advanceTimedReplay(displayTime: number): void {
    if (this._lastReplayDisplayTime !== null) {
      this._replayElapsedMs += Math.max(0, displayTime - this._lastReplayDisplayTime);
    }
    this._lastReplayDisplayTime = displayTime;

    const firstTime = this._replayFrames[0].timeMs;
    const lastTime = this._replayFrames[this._replayFrames.length - 1].timeMs;
    const duration = replayDuration(this._replayFrames);
    const elapsed =
      this._loopReplay && duration > 0 ? this._replayElapsedMs % duration : this._replayElapsedMs;
    const sampleTime = Math.min(firstTime + elapsed, lastTime);
    const sample = sampleAtTime(this._replayFrames, sampleTime);
    this._currentFrame = sample.frame;
    this._replayIndex = sample.index;
  }

  /**
   * Return a replaying XRFrame view for CloudXR tracking only. No global WebXR
   * objects are modified, and callers retain the original frame for rendering.
   */
  adaptTrackingFrame = (frame: XRFrame): XRFrame => {
    if (this._trackingSession?.nativeSession !== frame.session) {
      this._trackingSession?.dispose();
      this._trackingSession = new XRReplaySession(frame.session);
    }
    const replaying = this._mode === 'replaying';
    this._trackingSession.setInputSources(
      replaying ? this._replayInputSources(frame.session) : null
    );
    const session = this._trackingSession.session;
    // Waiting for calibration must not silently substitute live robot inputs.
    const replay = this._currentFrame ?? emptyFrame(0);

    return new Proxy(frame, {
      get: (target, property) => {
        if (property === 'session') return session;
        if (replaying && property === 'getPose') {
          return (space: XRSpace, baseSpace: XRSpace) =>
            this._replayPose(target, replay, space, baseSpace);
        }
        if (replaying && property === 'getJointPose') {
          return (joint: XRJointSpace, baseSpace: XRSpace) =>
            this._replayJoint(target, replay, joint, baseSpace);
        }
        return bindWebXRMember(target, property);
      },
    });
  };

  exportJSON(): string {
    return JSON.stringify(this.getRecording());
  }

  static importJSON(json: string): Recording {
    let parsed: unknown;
    try {
      parsed = JSON.parse(json);
    } catch {
      throw new Error('File is not valid JSON');
    }
    if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
      throw new Error('Malformed recording: expected a JSON object');
    }
    const recording = parsed as Recording;
    if (recording.version !== 1) {
      throw new Error(`Unsupported recording version: ${recording.version}`);
    }
    if (!Array.isArray(recording.frames)) {
      throw new Error('Malformed recording: frames is not an array');
    }
    if (
      recording.calibration !== undefined &&
      (typeof recording.calibration !== 'object' ||
        recording.calibration === null ||
        recording.calibration.mode !== 'viewer-start-yaw' ||
        !isPoseData(recording.calibration.pose))
    ) {
      throw new Error('Malformed recording: calibration is invalid');
    }
    let previousTime = -1;
    for (const frame of recording.frames) {
      if (!Number.isFinite(frame?.timeMs) || frame.timeMs < 0 || frame.timeMs < previousTime) {
        throw new Error('Malformed recording: frame timeMs must be finite and monotonic');
      }
      previousTime = frame.timeMs;
    }
    return recording;
  }

  getRecording(): Recording {
    const recording: Recording = {
      version: 1,
      recordedAt: this._recordedAt,
      calibration: this._recordingCalibration,
      frames: [...this._frames],
    };
    if (this._recordingAlignment) {
      this._alignmentCache.set(recording, this._recordingAlignment);
    }
    return recording;
  }

  private _assertIdle(): void {
    if (this._mode !== 'idle') {
      throw new Error('XRInputRecorder: already active');
    }
  }

  private _observeReferenceSpace(
    session: XRSession,
    referenceSpace: XRReferenceSpace | null
  ): void {
    if (session === this._observedSession && referenceSpace === this._observedReferenceSpace) {
      return;
    }

    this._observedReferenceSpace?.removeEventListener?.('reset', this._onReferenceSpaceReset);
    this._interruptRecording();
    this._invalidateAlignments();
    this._observedSession = session;
    this._observedReferenceSpace = referenceSpace;
    this._sceneReferenceSpace = referenceSpace;
    referenceSpace?.addEventListener?.('reset', this._onReferenceSpaceReset);
  }

  private _interruptRecording(): void {
    if (this._mode === 'recording' && this._frames.length > 0) {
      // One recording must not mix coordinates from different reference-space origins.
      this.stopRecording();
      this._recordingInterrupted = true;
    }
  }

  private _invalidateAlignments(): void {
    this._alignmentCache = new WeakMap<Recording, PoseData>();
    this._recordingAlignment = null;
    this._currentFromInitial = IDENTITY_POSE;
    this._replaySceneAlignment = null;
    this._calibrationRequested = false;
    this._lastReplayDisplayTime = null;
    this._currentFrame = null;
  }

  private _onReferenceSpaceReset = (event: XRReferenceSpaceEvent): void => {
    this._interruptRecording();
    if (!event.transform) {
      this._invalidateAlignments();
      return;
    }

    // The event gives oldScene <- newScene. Preserve world placement using its
    // inverse; the current viewer pose includes operator motion, not just drift.
    const oldFromNew = serializeTransform(event.transform);
    this._currentFromInitial = transformByPose(this._currentFromInitial, inversePose(oldFromNew));
    this._replaySceneAlignment = null;
    this._calibrationRequested = false;
    this._currentFrame = null;
  };

  private _prepareReplayAlignment(frame: XRFrame, referenceSpace: XRReferenceSpace): boolean {
    if (this._replaySceneAlignment) return true;
    const recording = this._replayRecording;
    if (!recording) return false;

    let initialFromRecorded = this._alignmentCache.get(recording);
    if (!initialFromRecorded) {
      let currentFromRecorded = IDENTITY_POSE;
      if (recording.calibration) {
        if (!this._calibrationRequested) return false;
        const currentCalibration = captureViewerCalibration(frame, referenceSpace);
        if (!currentCalibration) return false;
        currentFromRecorded = sceneAlignment(recording.calibration.pose, currentCalibration.pose);
      }
      initialFromRecorded = transformByPose(
        currentFromRecorded,
        inversePose(this._currentFromInitial)
      );
      this._alignmentCache.set(recording, initialFromRecorded);
      this._calibrationRequested = false;
    }

    this._replaySceneAlignment = transformByPose(initialFromRecorded, this._currentFromInitial);
    return true;
  }

  dispose(): void {
    this._trackingSession?.dispose();
    this._trackingSession = null;
    this._observedReferenceSpace?.removeEventListener?.('reset', this._onReferenceSpaceReset);
    this._observedReferenceSpace = null;
    this._observedSession = null;
    this._invalidateAlignments();
  }

  private _replayInputSources(session: XRSession): XRInputSource[] {
    const recordedHands = new Set(this._recordedHandSources.map(source => source.handedness));
    const sources = [
      ...this._recordedHandSources.filter(source => {
        const hand = source.handedness as 'left' | 'right';
        return Object.values(this._currentFrame?.handJoints[hand] ?? {}).some(Boolean);
      }),
      ...Array.from(session.inputSources).filter(source => !recordedHands.has(source.handedness)),
    ];
    return sources.map(source => {
      let proxy = this._sourceProxies.get(source);
      if (!proxy) {
        let lastGamepad: SerializedGamepad | null | undefined;
        let replayGamepad: Gamepad | null = null;
        proxy = new Proxy(source, {
          get: (target, property) => {
            const hand = target.handedness;
            if (property === 'gamepad' && (hand === 'left' || hand === 'right')) {
              const gamepad = this._currentFrame?.gamepads[hand];
              // WebXR gamepad identity is stable for repeated reads of one frame.
              if (gamepad !== lastGamepad) {
                replayGamepad = gamepad ? makeGamepad(gamepad) : null;
                lastGamepad = gamepad;
              }
              return replayGamepad;
            }
            return bindWebXRMember(target, property);
          },
        });
        this._sourceProxies.set(source, proxy);
      }
      return proxy;
    });
  }

  private _replayPose(
    frame: XRFrame,
    replay: RecordedFrame,
    space: XRSpace,
    baseSpace: XRSpace
  ): XRPose | undefined {
    for (const source of [...this._recordedHandSources, ...frame.session.inputSources]) {
      const hand = source.handedness;
      if (hand !== 'left' && hand !== 'right') continue;
      if (space === source.gripSpace) {
        return this._poseInBase(frame, replay.poses[`${hand}Grip`], baseSpace);
      }
      if (space === source.targetRaySpace) {
        return this._poseInBase(frame, replay.poses[`${hand}Aim`], baseSpace);
      }
    }
    return frame.getPose(space, baseSpace) ?? undefined;
  }

  private _replayJoint(
    frame: XRFrame,
    replay: RecordedFrame,
    joint: XRJointSpace,
    baseSpace: XRSpace
  ): XRJointPose | undefined {
    for (const source of [...this._recordedHandSources, ...frame.session.inputSources]) {
      const hand = source.handedness;
      if ((hand !== 'left' && hand !== 'right') || !source.hand) continue;
      for (const [name, candidate] of source.hand.entries()) {
        if (candidate !== joint) continue;
        const recorded = replay.handJoints[hand][name];
        const transformed = this._transformToBase(frame, recorded, baseSpace);
        return transformed ? makeJointPose(transformed) : undefined;
      }
    }
    return frame.getJointPose?.(joint, baseSpace) ?? undefined;
  }

  private _poseInBase(
    frame: XRFrame,
    pose: SerializedPose,
    baseSpace: XRSpace
  ): XRPose | undefined {
    const transformed = this._transformToBase(frame, pose, baseSpace);
    return transformed ? makePose(transformed) : undefined;
  }

  private _transformToBase<T extends PoseData>(
    frame: XRFrame,
    pose: T | null | undefined,
    baseSpace: XRSpace
  ): T | null {
    if (!pose || !this._sceneReferenceSpace) return null;
    if (!this._replaySceneAlignment) return null;
    const currentScenePose = transformByPose(pose, this._replaySceneAlignment);
    if (baseSpace === this._sceneReferenceSpace) return currentScenePose;
    const relation = frame.getPose(this._sceneReferenceSpace, baseSpace);
    return relation ? transformFromScene(currentScenePose, relation.transform) : null;
  }
}
