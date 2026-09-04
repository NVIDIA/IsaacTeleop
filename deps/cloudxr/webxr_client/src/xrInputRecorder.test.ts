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

import { type RecordedFrame, type Recording, XRInputRecorder } from './xrInputRecorder';

class FakeRigidTransform {
  readonly position: DOMPointReadOnly;
  readonly orientation: DOMPointReadOnly;

  constructor(position: DOMPointInit = {}, orientation: DOMPointInit = { w: 1 }) {
    this.position = {
      x: position.x ?? 0,
      y: position.y ?? 0,
      z: position.z ?? 0,
      w: position.w ?? 1,
    } as DOMPointReadOnly;
    this.orientation = {
      x: orientation.x ?? 0,
      y: orientation.y ?? 0,
      z: orientation.z ?? 0,
      w: orientation.w ?? 1,
    } as DOMPointReadOnly;
  }
}

const sceneSpace = {} as XRReferenceSpace;

function pose(x: number, y = 0, z = 0, orientation: DOMPointInit = { w: 1 }): XRPose {
  return {
    transform: new FakeRigidTransform({ x, y, z, w: 1 }, orientation),
    emulatedPosition: false,
    linearVelocity: null,
    angularVelocity: null,
  } as unknown as XRPose;
}

function jointPose(x: number, radius = 0.01): XRJointPose {
  return { ...pose(x), radius } as XRJointPose;
}

function gamepad(axis: number): Gamepad {
  return {
    axes: [axis],
    buttons: [{ value: axis, pressed: axis > 0, touched: true }],
  } as unknown as Gamepad;
}

function makeSession(inputSources: XRInputSource[] = []): XRSession {
  return { inputSources } as unknown as XRSession;
}

type PoseResolver = (space: XRSpace, baseSpace: XRSpace) => XRPose | null;
type JointResolver = (joint: XRJointSpace, baseSpace: XRSpace) => XRJointPose | null;

function makeFrame(
  inputSources: XRInputSource[] = [],
  getPose: PoseResolver = () => null,
  getJointPose: JointResolver = () => null,
  predictedDisplayTime = 0,
  viewerPose: XRPose | null = pose(0),
  session: XRSession = makeSession(inputSources)
): XRFrame {
  return {
    session,
    predictedDisplayTime,
    getPose,
    getJointPose,
    getViewerPose: () => viewerPose,
  } as unknown as XRFrame;
}

function frameData(x = 0): RecordedFrame {
  return {
    timeMs: x,
    poses: {
      leftGrip: { px: x, py: 0, pz: 0, ox: 0, oy: 0, oz: 0, ow: 1 },
      leftAim: { px: x + 1, py: 0, pz: 0, ox: 0, oy: 0, oz: 0, ow: 1 },
      rightGrip: null,
      rightAim: null,
    },
    gamepads: {
      left: { axes: [x], buttons: [{ value: x, pressed: true, touched: true }] },
      right: null,
    },
    handJoints: {
      left: {
        wrist: { px: x + 2, py: 0, pz: 0, ox: 0, oy: 0, oz: 0, ow: 1, radius: 0.02 },
      },
      right: {},
    },
  };
}

function recording(...frames: RecordedFrame[]): Recording {
  return { version: 1, frames };
}

function calibratedRecording(viewerX: number, ...frames: RecordedFrame[]): Recording {
  return {
    version: 1,
    calibration: {
      mode: 'viewer-start-yaw',
      pose: { px: viewerX, py: 0, pz: 0, ox: 0, oy: 0, oz: 0, ow: 1 },
    },
    frames,
  };
}

function timedFrame(timeMs: number, x: number): RecordedFrame {
  return { ...frameData(x), timeMs };
}

function recordFrames(count: number): Recording {
  const recorder = new XRInputRecorder();
  recorder.startRecording();
  for (let index = 0; index < count; index++) {
    recorder.beginFrame(makeFrame(), sceneSpace);
  }
  recorder.stopRecording();
  return recorder.getRecording();
}

beforeAll(() => {
  (global as { XRRigidTransform?: unknown }).XRRigidTransform = FakeRigidTransform;
});

describe('lifecycle and frame advancement', () => {
  test('records frames and returns to idle', () => {
    const recorder = new XRInputRecorder();
    recorder.startRecording();
    recorder.beginFrame(makeFrame(), sceneSpace);
    recorder.beginFrame(makeFrame(), sceneSpace);
    expect(recorder.mode).toBe('recording');
    expect(recorder.recordedFrameCount).toBe(2);

    recorder.stopRecording();
    expect(recorder.mode).toBe('idle');
    expect(recorder.currentFrame).toBeNull();
    expect(recorder.getRecording().frames).toHaveLength(2);
  });

  test.each(['recording', 'replaying'] as const)(
    'rejects starting another operation while %s',
    mode => {
      const recorder = new XRInputRecorder();
      if (mode === 'recording') recorder.startRecording();
      else recorder.startReplay(recording(frameData()));
      expect(() => recorder.startRecording()).toThrow(/already active/);
    }
  );

  test('does not record or advance replay while disconnected', () => {
    const recorder = new XRInputRecorder();
    recorder.startRecording();
    recorder.beginFrame(makeFrame(), sceneSpace, false);
    expect(recorder.recordedFrameCount).toBe(0);
    recorder.stopRecording();

    recorder.startReplay(recording(frameData(1), frameData(2)));
    recorder.beginFrame(makeFrame(), sceneSpace, false);
    expect(recorder.replayFrameIndex).toBe(0);
    expect(recorder.currentFrame).toBeNull();
  });

  test('loops replay by frame and can clamp at the final frame', () => {
    const looped = new XRInputRecorder();
    looped.startReplay(recording(frameData(1), frameData(2)), true, 'frame');
    looped.beginFrame(makeFrame(), sceneSpace);
    looped.beginFrame(makeFrame(), sceneSpace);
    expect(looped.replayFrameIndex).toBe(0);

    const clamped = new XRInputRecorder();
    clamped.startReplay(recording(frameData(1), frameData(2)), false, 'frame');
    clamped.beginFrame(makeFrame(), sceneSpace);
    clamped.beginFrame(makeFrame(), sceneSpace);
    clamped.beginFrame(makeFrame(), sceneSpace);
    expect(clamped.currentFrame).toEqual(frameData(2));
    expect(clamped.replayFrameIndex).toBe(1);
  });

  test('time-paces replay by default and interpolates timestamped samples', () => {
    const first = timedFrame(0, 0);
    first.gamepads.left!.buttons[0].pressed = false;
    const second = timedFrame(100, 10);
    second.poses.leftGrip = {
      ...second.poses.leftGrip!,
      oz: 1,
      ow: 0,
    };

    const recorder = new XRInputRecorder();
    recorder.startReplay(recording(first, second), false);
    recorder.beginFrame(makeFrame([], undefined, undefined, 1000), sceneSpace);
    recorder.beginFrame(makeFrame([], undefined, undefined, 1050), sceneSpace);

    expect(recorder.currentFrame?.timeMs).toBe(50);
    expect(recorder.currentFrame?.poses.leftGrip?.px).toBe(5);
    expect(recorder.currentFrame?.poses.leftGrip?.oz).toBeCloseTo(Math.sqrt(0.5));
    expect(recorder.currentFrame?.poses.leftGrip?.ow).toBeCloseTo(Math.sqrt(0.5));
    expect(recorder.currentFrame?.gamepads.left?.axes).toEqual([5]);
    expect(recorder.currentFrame?.gamepads.left?.buttons[0].pressed).toBe(false);
    expect(recorder.currentFrame?.handJoints.left.wrist?.px).toBe(7);
  });

  test('holds the earlier gamepad sample when controller layouts differ', () => {
    const first = timedFrame(0, 0);
    const second = timedFrame(100, 10);
    second.gamepads.left!.axes.push(20);
    second.gamepads.left!.buttons.push({ value: 20, pressed: true, touched: true });

    const recorder = new XRInputRecorder();
    recorder.startReplay(recording(first, second), false);
    recorder.beginFrame(makeFrame([], undefined, undefined, 1000), sceneSpace);
    recorder.beginFrame(makeFrame([], undefined, undefined, 1050), sceneSpace);

    expect(recorder.currentFrame?.gamepads.left).toEqual(first.gamepads.left);
  });

  test('holds the final timed sample before looping', () => {
    const recorder = new XRInputRecorder();
    recorder.startReplay(recording(timedFrame(0, 0), timedFrame(100, 10)), true, 'time');

    recorder.beginFrame(makeFrame([], undefined, undefined, 1000), sceneSpace);
    recorder.beginFrame(makeFrame([], undefined, undefined, 1100), sceneSpace);
    expect(recorder.currentFrame).toEqual(timedFrame(100, 10));

    recorder.beginFrame(makeFrame([], undefined, undefined, 1150), sceneSpace);
    expect(recorder.currentFrame).toEqual(timedFrame(100, 10));

    recorder.beginFrame(makeFrame([], undefined, undefined, 1200), sceneSpace);
    expect(recorder.currentFrame).toEqual(timedFrame(0, 0));
  });

  test('pauses time-paced replay while advancement is gated off', () => {
    const recorder = new XRInputRecorder();
    recorder.startReplay(recording(timedFrame(0, 0), timedFrame(100, 10)), false, 'time');

    recorder.beginFrame(makeFrame([], undefined, undefined, 1000), sceneSpace);
    recorder.beginFrame(makeFrame([], undefined, undefined, 1040), sceneSpace);
    recorder.beginFrame(makeFrame([], undefined, undefined, 1100), sceneSpace, false);
    recorder.beginFrame(makeFrame([], undefined, undefined, 2000), sceneSpace);
    expect(recorder.currentFrame?.poses.leftGrip?.px).toBe(4);

    recorder.beginFrame(makeFrame([], undefined, undefined, 2020), sceneSpace);
    expect(recorder.currentFrame?.poses.leftGrip?.px).toBe(6);
  });

  test('captures live input while idle only when requested', () => {
    const recorder = new XRInputRecorder();
    recorder.beginFrame(makeFrame(), sceneSpace, true, false);
    expect(recorder.currentFrame).toBeNull();
    recorder.beginFrame(makeFrame(), sceneSpace, true, true);
    expect(recorder.currentFrame).toEqual({
      timeMs: 0,
      poses: { leftGrip: null, leftAim: null, rightGrip: null, rightAim: null },
      gamepads: { left: null, right: null },
      handJoints: { left: {}, right: {} },
    });
  });
});

describe('canonical scene-space capture', () => {
  test('captures grip, aim, gamepad, and joints by WebXR joint name', () => {
    const grip = {} as XRSpace;
    const aim = {} as XRSpace;
    const wrist = {} as XRJointSpace;
    const indexTip = {} as XRJointSpace;
    const source = {
      handedness: 'left',
      gripSpace: grip,
      targetRaySpace: aim,
      gamepad: gamepad(0.75),
      hand: new Map([
        ['wrist', wrist],
        ['index-finger-tip', indexTip],
      ]),
    } as unknown as XRInputSource;
    const frame = makeFrame(
      [source],
      space => (space === grip ? pose(1) : space === aim ? pose(2) : null),
      joint => (joint === wrist ? jointPose(3) : jointPose(4))
    );

    const recorder = new XRInputRecorder();
    recorder.startRecording();
    recorder.beginFrame(frame, sceneSpace);
    const captured = recorder.currentFrame!;

    expect(captured.poses.leftGrip?.px).toBe(1);
    expect(captured.poses.leftAim?.px).toBe(2);
    expect(captured.gamepads.left?.axes).toEqual([0.75]);
    expect(captured.handJoints.left.wrist?.px).toBe(3);
    expect(captured.handJoints.left['index-finger-tip']?.px).toBe(4);
  });

  test('captures a gravity-aligned viewer pose for cross-session calibration', () => {
    const quarterTurn = Math.sqrt(0.5);
    const recorder = new XRInputRecorder();
    recorder.startRecording();
    recorder.beginFrame(
      makeFrame([], undefined, undefined, 0, pose(1, 2, 3, { y: quarterTurn, w: quarterTurn })),
      sceneSpace
    );
    recorder.stopRecording();

    const calibration = recorder.getRecording().calibration;
    expect(calibration?.mode).toBe('viewer-start-yaw');
    expect(calibration?.pose).toMatchObject({ px: 1, py: 2, pz: 3, ox: 0, oz: 0 });
    expect(calibration?.pose.oy).toBeCloseTo(quarterTurn);
    expect(calibration?.pose.ow).toBeCloseTo(quarterTurn);
  });

  test('waits for a viewer pose before recording the first frame', () => {
    const recorder = new XRInputRecorder();
    recorder.startRecording();
    recorder.beginFrame(makeFrame([], undefined, undefined, 0, null), sceneSpace);
    expect(recorder.recordedFrameCount).toBe(0);

    recorder.beginFrame(makeFrame([], undefined, undefined, 1, pose(0)), sceneSpace);
    expect(recorder.recordedFrameCount).toBe(1);
  });
});

describe('scoped CloudXR replay frame', () => {
  test('does not alter global prototypes and returns real frames outside replay', () => {
    const recorder = new XRInputRecorder();
    const frame = makeFrame();
    const originalGetPose = frame.getPose;
    recorder.startRecording();
    expect(recorder.adaptTrackingFrame(frame)).toBe(frame);
    expect(frame.getPose).toBe(originalGetPose);
    recorder.stopRecording();
  });

  test('transforms recorded grip and aim from scene space into the requested base space', () => {
    const grip = {} as XRSpace;
    const aim = {} as XRSpace;
    const cloudSpace = {} as XRSpace;
    const source = {
      handedness: 'left',
      gripSpace: grip,
      targetRaySpace: aim,
      gamepad: gamepad(99),
    } as XRInputSource;
    const quarterTurn = Math.sqrt(0.5);
    const frame = makeFrame([source], (space, base) => {
      if (space === sceneSpace && base === cloudSpace) {
        return pose(10, 0, 0, { z: quarterTurn, w: quarterTurn });
      }
      return pose(99);
    });
    const recorder = new XRInputRecorder();
    recorder.startReplay(recording(frameData(1)));
    recorder.beginFrame(frame, sceneSpace);

    const adapted = recorder.adaptTrackingFrame(frame);
    const replayedGrip = adapted.getPose(grip, cloudSpace)!;
    const replayedAim = adapted.getPose(aim, cloudSpace)!;

    expect(frame.getPose(grip, cloudSpace)?.transform.position.x).toBe(99);
    expect(replayedGrip.transform.position.x).toBeCloseTo(10);
    expect(replayedGrip.transform.position.y).toBeCloseTo(1);
    expect(replayedAim.transform.position.y).toBeCloseTo(2);
    expect(replayedGrip.transform.orientation.z).toBeCloseTo(quarterTurn);
  });

  test('replays gamepads and joints without changing the real input source', () => {
    const grip = {} as XRSpace;
    const wrist = {} as XRJointSpace;
    const cloudSpace = {} as XRSpace;
    const source = {
      handedness: 'left',
      gripSpace: grip,
      targetRaySpace: {} as XRSpace,
      gamepad: gamepad(99),
      hand: new Map([['wrist', wrist]]),
    } as unknown as XRInputSource;
    const frame = makeFrame(
      [source],
      (space, base) => (space === sceneSpace && base === cloudSpace ? pose(10) : null),
      () => jointPose(99)
    );
    const recorder = new XRInputRecorder();
    recorder.startReplay(recording(frameData(3)));
    recorder.beginFrame(frame, sceneSpace);

    const adapted = recorder.adaptTrackingFrame(frame);
    const replaySources = adapted.session.inputSources;
    expect(source.gamepad?.axes).toEqual([99]);
    expect(adapted.session.inputSources).toBe(replaySources);
    expect(replaySources[0].gamepad).toBe(replaySources[0].gamepad);
    expect(replaySources[0].gamepad?.axes).toEqual([3]);
    expect(adapted.getJointPose?.(wrist, cloudSpace)?.transform.position.x).toBe(15);
    expect(adapted.getJointPose?.(wrist, cloudSpace)?.radius).toBe(0.02);
  });

  test('delegates unknown spaces and joints to the real frame', () => {
    const unknownSpace = {} as XRSpace;
    const unknownJoint = {} as XRJointSpace;
    const frame = makeFrame(
      [],
      () => pose(7),
      () => jointPose(8)
    );
    const recorder = new XRInputRecorder();
    recorder.startReplay(recording(frameData()));
    recorder.beginFrame(frame, sceneSpace);
    const adapted = recorder.adaptTrackingFrame(frame);

    expect(adapted.getPose(unknownSpace, sceneSpace)?.transform.position.x).toBe(7);
    expect(adapted.getJointPose?.(unknownJoint, sceneSpace)?.transform.position.x).toBe(8);
  });

  test('aligns loaded poses from the recorded viewer origin to the current XR session', () => {
    const grip = {} as XRSpace;
    const source = {
      handedness: 'left',
      gripSpace: grip,
      targetRaySpace: {} as XRSpace,
    } as XRInputSource;
    const session = makeSession([source]);
    const loaded = XRInputRecorder.importJSON(JSON.stringify(calibratedRecording(1, frameData(2))));
    const frame = makeFrame([source], undefined, undefined, 0, pose(11, 5), session);
    const recorder = new XRInputRecorder();
    recorder.startReplay(loaded, true, 'frame');
    recorder.beginFrame(frame, sceneSpace);

    const replayed = recorder.adaptTrackingFrame(frame).getPose(grip, sceneSpace);
    expect(replayed?.transform.position.x).toBeCloseTo(12);
    expect(replayed?.transform.position.y).toBeCloseTo(5);
  });

  test('applies the calibrated heading to replayed poses', () => {
    const grip = {} as XRSpace;
    const source = {
      handedness: 'left',
      gripSpace: grip,
      targetRaySpace: {} as XRSpace,
    } as XRInputSource;
    const session = makeSession([source]);
    const sample = frameData();
    sample.poses.leftGrip = { px: 0, py: 0, pz: -1, ox: 0, oy: 0, oz: 0, ow: 1 };
    const loaded = XRInputRecorder.importJSON(JSON.stringify(calibratedRecording(0, sample)));
    const quarterTurn = Math.sqrt(0.5);
    const frame = makeFrame(
      [source],
      undefined,
      undefined,
      0,
      pose(0, 0, 0, { y: quarterTurn, w: quarterTurn }),
      session
    );
    const recorder = new XRInputRecorder();
    recorder.startReplay(loaded, true, 'frame');
    recorder.beginFrame(frame, sceneSpace);

    const replayed = recorder.adaptTrackingFrame(frame).getPose(grip, sceneSpace);
    expect(replayed?.transform.position.x).toBeCloseTo(-1);
    expect(replayed?.transform.position.z).toBeCloseTo(0);
    expect(replayed?.transform.orientation.y).toBeCloseTo(quarterTurn);
    expect(replayed?.transform.orientation.w).toBeCloseTo(quarterTurn);
  });

  test('freezes calibration within a session and recalibrates for a new session', () => {
    const grip = {} as XRSpace;
    const source = {
      handedness: 'left',
      gripSpace: grip,
      targetRaySpace: {} as XRSpace,
    } as XRInputSource;
    const firstSession = makeSession([source]);
    const secondSession = makeSession([source]);
    const loaded = XRInputRecorder.importJSON(JSON.stringify(calibratedRecording(1, frameData(2))));
    const recorder = new XRInputRecorder();

    const firstFrame = makeFrame([source], undefined, undefined, 0, pose(11), firstSession);
    recorder.startReplay(loaded, true, 'frame');
    recorder.beginFrame(firstFrame, sceneSpace);
    expect(
      recorder.adaptTrackingFrame(firstFrame).getPose(grip, sceneSpace)?.transform.position.x
    ).toBeCloseTo(12);
    recorder.stopReplay();

    const movedViewerFrame = makeFrame([source], undefined, undefined, 1, pose(21), firstSession);
    recorder.startReplay(loaded, true, 'frame');
    recorder.beginFrame(movedViewerFrame, sceneSpace);
    expect(
      recorder.adaptTrackingFrame(movedViewerFrame).getPose(grip, sceneSpace)?.transform.position.x
    ).toBeCloseTo(12);
    recorder.stopReplay();

    const newSessionFrame = makeFrame([source], undefined, undefined, 2, pose(21), secondSession);
    recorder.startReplay(loaded, true, 'frame');
    recorder.beginFrame(newSessionFrame, sceneSpace);
    expect(
      recorder.adaptTrackingFrame(newSessionFrame).getPose(grip, sceneSpace)?.transform.position.x
    ).toBeCloseTo(22);
  });

  test('keeps in-memory recording and replay in the same reference space unchanged', () => {
    const grip = {} as XRSpace;
    const source = {
      handedness: 'left',
      gripSpace: grip,
      targetRaySpace: {} as XRSpace,
    } as XRInputSource;
    const session = makeSession([source]);
    const recordingFrame = makeFrame(
      [source],
      space => (space === grip ? pose(2) : null),
      undefined,
      0,
      pose(1),
      session
    );
    const recorder = new XRInputRecorder();
    recorder.startRecording();
    recorder.beginFrame(recordingFrame, sceneSpace);
    recorder.stopRecording();
    const saved = recorder.getRecording();

    const replayFrame = makeFrame([source], undefined, undefined, 1, pose(11), session);
    recorder.startReplay(saved, true, 'frame');
    recorder.beginFrame(replayFrame, sceneSpace);

    const replayed = recorder.adaptTrackingFrame(replayFrame).getPose(grip, sceneSpace);
    expect(replayed?.transform.position.x).toBeCloseTo(2);
  });
});

describe('serialization', () => {
  test('round-trips version 1 recordings', () => {
    const recorder = new XRInputRecorder();
    recorder.startRecording();
    recorder.beginFrame(makeFrame(), sceneSpace);
    recorder.stopRecording();
    const imported = XRInputRecorder.importJSON(recorder.exportJSON());
    expect(imported.frames).toHaveLength(1);
    expect(imported.calibration?.mode).toBe('viewer-start-yaw');
    expect(typeof recorder.getRecording().recordedAt).toBe('number');
  });

  test('records relative XR frame timing', () => {
    const recorder = new XRInputRecorder();
    recorder.startRecording();
    recorder.beginFrame(makeFrame([], undefined, undefined, 100), sceneSpace);
    recorder.beginFrame(makeFrame([], undefined, undefined, 116.5), sceneSpace);
    recorder.stopRecording();

    expect(recorder.getRecording().frames.map(frame => frame.timeMs)).toEqual([0, 16.5]);
  });

  test('records finite monotonic timeMs when predictedDisplayTime is missing', () => {
    // PICO leaves predictedDisplayTime undefined; without a fallback timeMs was
    // NaN -> serialized to null -> rejected on import.
    const noTime = undefined as unknown as number;
    const recorder = new XRInputRecorder();
    recorder.startRecording();
    recorder.beginFrame(makeFrame([], undefined, undefined, noTime), sceneSpace);
    recorder.beginFrame(makeFrame([], undefined, undefined, noTime), sceneSpace);
    recorder.stopRecording();

    const times = recorder.getRecording().frames.map(frame => frame.timeMs);
    expect(times.every(t => Number.isFinite(t) && t >= 0)).toBe(true);
    expect(times[1]).toBeGreaterThanOrEqual(times[0]);
    expect(() => XRInputRecorder.importJSON(recorder.exportJSON())).not.toThrow();
  });

  test.each([
    { version: 2, frames: [] },
    { version: 1, frames: null },
    { version: 1, frames: [{ ...frameData(), timeMs: undefined }] },
    { version: 1, frames: [frameData(2), frameData(1)] },
    { version: 1, calibration: { mode: 'viewer-start-yaw', pose: {} }, frames: [] },
    { version: 1, calibration: { mode: 'unknown', pose: {} }, frames: [] },
    null,
    42,
    [],
  ])('rejects incompatible or malformed recordings', value => {
    expect(() => XRInputRecorder.importJSON(JSON.stringify(value))).toThrow();
  });

  test('rejects non-JSON input with a clear message', () => {
    expect(() => XRInputRecorder.importJSON('not json {')).toThrow('File is not valid JSON');
  });

  test('returns a recording snapshot', () => {
    const recorder = new XRInputRecorder();
    recorder.startRecording();
    recorder.beginFrame(makeFrame(), sceneSpace);
    recorder.stopRecording();
    const snapshot = recorder.getRecording();
    recorder.startRecording();
    recorder.beginFrame(makeFrame(), sceneSpace);
    recorder.beginFrame(makeFrame(), sceneSpace);
    expect(snapshot.frames).toHaveLength(1);
  });

  test('helper can create recordings for replay tests', () => {
    expect(recordFrames(3).frames).toHaveLength(3);
  });
});
