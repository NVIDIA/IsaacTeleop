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
 * Unit tests for XRInputRecorder.
 *
 * WebXR globals (XRFrame, XRSession) don't exist in node — minimal stubs are
 * installed as globals before any test that calls startRecording/startReplay.
 */

import { XRInputRecorder, type Recording } from './xrInputRecorder';

// ---- minimal WebXR stubs ---------------------------------------------------

class FakeXRSession {
  inputSources: XRInputSource[] = [];
}

class FakeXRFrame {
  readonly session: FakeXRSession;
  constructor(session: FakeXRSession) {
    this.session = session;
  }
  getPose(_space: unknown, _ref: unknown): XRPose | null {
    return null;
  }
  getJointPose(_joint: unknown, _ref: unknown): XRJointPose | null {
    return null;
  }
}

function makeFrame(sources: Partial<XRInputSource>[] = []): XRFrame {
  const session = new FakeXRSession();
  session.inputSources = sources as XRInputSource[];
  return new FakeXRFrame(session) as unknown as XRFrame;
}

/** Record N frames and return the resulting Recording. */
function makeRecording(frameCount: number): Recording {
  const r = new XRInputRecorder();
  r.startRecording();
  for (let i = 0; i < frameCount; i++) r.beginFrame(makeFrame());
  r.stopRecording();
  return r.getRecording();
}

beforeAll(() => {
  (global as any).XRFrame = FakeXRFrame;
  (global as any).XRSession = FakeXRSession;
});

// ---- mode state machine ----------------------------------------------------

describe('mode transitions', () => {
  test('starts idle', () => {
    const r = new XRInputRecorder();
    expect(r.mode).toBe('idle');
  });

  test('idle → recording → idle', () => {
    const r = new XRInputRecorder();
    r.startRecording();
    expect(r.mode).toBe('recording');
    r.stopRecording();
    expect(r.mode).toBe('idle');
  });

  test('idle → replaying → idle', () => {
    const r = new XRInputRecorder();
    r.startReplay(makeRecording(1));
    expect(r.mode).toBe('replaying');
    r.stopReplay();
    expect(r.mode).toBe('idle');
  });

  test('startRecording throws when already active', () => {
    const r = new XRInputRecorder();
    r.startRecording();
    expect(() => r.startRecording()).toThrow();
    r.stopRecording();
  });

  test('startReplay throws when already active', () => {
    const r = new XRInputRecorder();
    r.startReplay(makeRecording(1));
    expect(() => r.startReplay(makeRecording(1))).toThrow();
    r.stopReplay();
  });

  test('stopRecording is safe when idle', () => {
    const r = new XRInputRecorder();
    expect(() => r.stopRecording()).not.toThrow();
  });

  test('stopReplay is safe when idle', () => {
    const r = new XRInputRecorder();
    expect(() => r.stopReplay()).not.toThrow();
  });
});

// ---- frame accumulation -----------------------------------------------------

describe('recordedFrameCount', () => {
  test('zero before first recording', () => {
    const r = new XRInputRecorder();
    expect(r.recordedFrameCount).toBe(0);
  });

  test('increments with each beginFrame', () => {
    const r = new XRInputRecorder();
    r.startRecording();
    r.beginFrame(makeFrame());
    expect(r.recordedFrameCount).toBe(1);
    r.beginFrame(makeFrame());
    expect(r.recordedFrameCount).toBe(2);
    r.stopRecording();
  });

  test('resets to 0 on a second startRecording', () => {
    const r = new XRInputRecorder();
    r.startRecording();
    r.beginFrame(makeFrame());
    r.stopRecording();
    r.startRecording();
    expect(r.recordedFrameCount).toBe(0);
    r.stopRecording();
  });

  test('getRecording frames length matches recordedFrameCount', () => {
    const r = new XRInputRecorder();
    r.startRecording();
    for (let i = 0; i < 7; i++) r.beginFrame(makeFrame());
    const count = r.recordedFrameCount;
    r.stopRecording();
    expect(r.getRecording().frames).toHaveLength(count);
  });
});

// ---- currentFrame -----------------------------------------------------------

describe('currentFrame', () => {
  test('null in idle mode', () => {
    expect(new XRInputRecorder().currentFrame).toBeNull();
  });

  test('null before first beginFrame during recording', () => {
    const r = new XRInputRecorder();
    r.startRecording();
    expect(r.currentFrame).toBeNull();
    r.stopRecording();
  });

  test('non-null after beginFrame during recording', () => {
    const r = new XRInputRecorder();
    r.startRecording();
    r.beginFrame(makeFrame());
    expect(r.currentFrame).not.toBeNull();
    r.stopRecording();
  });

  test('null after stopRecording', () => {
    const r = new XRInputRecorder();
    r.startRecording();
    r.beginFrame(makeFrame());
    r.stopRecording();
    expect(r.currentFrame).toBeNull();
  });

  test('non-null during replay after beginFrame', () => {
    const r = new XRInputRecorder();
    r.startReplay(makeRecording(2));
    r.beginFrame(makeFrame());
    expect(r.currentFrame).not.toBeNull();
    r.stopReplay();
  });

  test('null after stopReplay', () => {
    const r = new XRInputRecorder();
    r.startReplay(makeRecording(1));
    r.beginFrame(makeFrame());
    r.stopReplay();
    expect(r.currentFrame).toBeNull();
  });
});

// ---- replay frame advancement -----------------------------------------------

describe('replay frame advancement', () => {
  test('advances index each beginFrame', () => {
    const r = new XRInputRecorder();
    r.startReplay(makeRecording(3));
    expect(r.replayFrameIndex).toBe(0);
    r.beginFrame(makeFrame());
    expect(r.replayFrameIndex).toBe(1);
    r.beginFrame(makeFrame());
    expect(r.replayFrameIndex).toBe(2);
    r.stopReplay();
  });

  test('loops when loop=true (default)', () => {
    const r = new XRInputRecorder();
    r.startReplay(makeRecording(2), true);
    r.beginFrame(makeFrame()); // consumes frame 0 → index 1
    r.beginFrame(makeFrame()); // consumes frame 1 → wraps to 0
    expect(r.replayFrameIndex).toBe(0);
    r.stopReplay();
  });

  test('clamps to last frame when loop=false', () => {
    const r = new XRInputRecorder();
    r.startReplay(makeRecording(2), false);
    r.beginFrame(makeFrame()); // index → 1
    r.beginFrame(makeFrame()); // index → clamped to 1 (last)
    r.beginFrame(makeFrame()); // stays at 1
    expect(r.replayFrameIndex).toBe(1);
    r.stopReplay();
  });

  test('does not advance when connected=false', () => {
    const r = new XRInputRecorder();
    r.startReplay(makeRecording(3));
    r.beginFrame(makeFrame(), false);
    r.beginFrame(makeFrame(), false);
    expect(r.replayFrameIndex).toBe(0);
    r.stopReplay();
  });

  test('beginFrame during recording does not advance replayFrameIndex', () => {
    const r = new XRInputRecorder();
    r.startRecording();
    r.beginFrame(makeFrame());
    r.beginFrame(makeFrame());
    r.stopRecording();
    expect(r.replayFrameIndex).toBe(0);
  });
});

// ---- serialization ----------------------------------------------------------

describe('exportJSON / importJSON', () => {
  test('round-trip preserves version and frame count', () => {
    const r = new XRInputRecorder();
    r.startRecording();
    for (let i = 0; i < 4; i++) r.beginFrame(makeFrame());
    r.stopRecording();
    const loaded = XRInputRecorder.importJSON(r.exportJSON());
    expect(loaded.version).toBe(1);
    expect(loaded.frames).toHaveLength(4);
  });

  test('importJSON throws on unsupported version', () => {
    expect(() =>
      XRInputRecorder.importJSON(JSON.stringify({ version: 99, frames: [] })),
    ).toThrow(/version/i);
  });
});

describe('getRecording', () => {
  test('returns a snapshot — further recording does not mutate it', () => {
    const r = new XRInputRecorder();
    r.startRecording();
    r.beginFrame(makeFrame());
    r.stopRecording();
    const snap = r.getRecording();
    const snapLen = snap.frames.length;

    r.startRecording();
    r.beginFrame(makeFrame());
    r.stopRecording();

    expect(snap.frames).toHaveLength(snapLen);
  });
});

// ---- prototype patching -----------------------------------------------------

describe('prototype patching', () => {
  test('startRecording replaces XRFrame.prototype.getPose', () => {
    const original = FakeXRFrame.prototype.getPose;
    const r = new XRInputRecorder();
    r.startRecording();
    expect(FakeXRFrame.prototype.getPose).not.toBe(original);
    r.stopRecording();
  });

  test('stopRecording restores XRFrame.prototype.getPose', () => {
    const original = FakeXRFrame.prototype.getPose;
    const r = new XRInputRecorder();
    r.startRecording();
    r.stopRecording();
    expect(FakeXRFrame.prototype.getPose).toBe(original);
  });

  test('startReplay replaces XRFrame.prototype.getPose', () => {
    const original = FakeXRFrame.prototype.getPose;
    const r = new XRInputRecorder();
    r.startReplay(makeRecording(1));
    expect(FakeXRFrame.prototype.getPose).not.toBe(original);
    r.stopReplay();
  });

  test('stopReplay restores XRFrame.prototype.getPose', () => {
    const original = FakeXRFrame.prototype.getPose;
    const r = new XRInputRecorder();
    r.startReplay(makeRecording(1));
    r.stopReplay();
    expect(FakeXRFrame.prototype.getPose).toBe(original);
  });
});
