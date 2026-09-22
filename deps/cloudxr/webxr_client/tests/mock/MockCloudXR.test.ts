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
 *
 * @jest-environment jsdom
 *
 * Jest only reads this pragma from the file's first comment block, hence its placement here.
 * The CloudXR SDK bundle touches `window` at import time (see metricsAccumulator.test.ts for
 * the same reasoning).
 *
 * MockCloudXR session-lifecycle tests: connect/disconnect/failure paths and the delegate calls
 * they drive. Analogous in spirit to cloudxr-js's tests/playwright/tests/react-session.test.ts
 * (which forces a mid-stream failure through ragnarok-mock and asserts the app's reaction), but
 * exercises MockCloudXR's CloudXR.Session surface directly through jest rather than a real
 * browser - this repo has no Playwright/browser-e2e harness, so a real transient failure is
 * simulated here via triggerFailure() the same way __cloudxrMockFail() does there.
 */

import * as CloudXR from '@nvidia/cloudxr';

import { createMockCloudXRSession, MockCloudXR, NullWebGLContext } from './MockCloudXR';

const referenceSpace = {} as XRReferenceSpace;
const gl = {} as WebGL2RenderingContext;

function makeSession(overrides: Partial<CloudXR.SessionOptions> = {}): {
  session: MockCloudXR;
  delegates: {
    onLog: jest.Mock;
    onStreamStarted: jest.Mock;
    onStreamStopped: jest.Mock;
    onStreamTestStarted: jest.Mock;
    onStreamTestStopped: jest.Mock;
    onMetrics: jest.Mock;
  };
} {
  const delegates = {
    onLog: jest.fn(),
    onStreamStarted: jest.fn(),
    onStreamStopped: jest.fn(),
    onStreamTestStarted: jest.fn(),
    onStreamTestStopped: jest.fn(),
    onMetrics: jest.fn(),
  };
  const session = createMockCloudXRSession(
    {
      serverAddress: 'mock',
      serverPort: 0,
      useSecureConnection: false,
      gl,
      perEyeWidth: 1024,
      perEyeHeight: 1024,
      referenceSpace,
      ...overrides,
    },
    delegates
  );
  return { session, delegates };
}

describe('MockCloudXR session lifecycle', () => {
  beforeEach(() => {
    jest.useFakeTimers();
  });

  afterEach(() => {
    jest.useRealTimers();
  });

  test('connect() reaches Connected and fires onStreamStarted', () => {
    const { session, delegates } = makeSession();
    session.connectWait(0);

    session.connect();
    expect(session.state).toBe(CloudXR.SessionState.Connecting);
    expect(delegates.onStreamStarted).not.toHaveBeenCalled();

    jest.advanceTimersByTime(0);

    expect(session.state).toBe(CloudXR.SessionState.Connected);
    expect(delegates.onStreamStarted).toHaveBeenCalledTimes(1);
    expect(delegates.onLog).toHaveBeenCalled();
  });

  test('sendTrackingStateToServer() throws before connect()', () => {
    const { session } = makeSession();
    const frame = {} as unknown as XRFrame;

    expect(() => session.sendTrackingStateToServer(0, frame)).toThrow();
  });

  test('sendTrackingStateToServer() returns false while still Connecting', () => {
    const { session } = makeSession();
    const frame = {} as unknown as XRFrame;

    session.connect();
    expect(session.sendTrackingStateToServer(0, frame)).toBe(false);
  });

  test('disconnect() fires onStreamStopped(undefined) and returns to Disconnected', () => {
    const { session, delegates } = makeSession();
    session.connectWait(0);
    session.connect();
    jest.advanceTimersByTime(0);

    session.disconnect();

    expect(session.state).toBe(CloudXR.SessionState.Disconnected);
    expect(delegates.onStreamStopped).toHaveBeenCalledWith(undefined);
  });

  test('triggerFailure() ends the session with an error, as a dropped connection would', () => {
    // Analogous to react-session.test.ts's window.__cloudxrMockFail(): forces the same
    // onStreamStopped(error) path a real mid-stream failure would take.
    const { session, delegates } = makeSession();
    session.connectWait(0);
    session.connect();
    jest.advanceTimersByTime(0);

    session.triggerFailure({ name: 'StreamingError', message: 'mock network error' });

    expect(session.state).toBe(CloudXR.SessionState.Error);
    expect(delegates.onStreamStopped).toHaveBeenCalledTimes(1);
    const [error] = delegates.onStreamStopped.mock.calls[0];
    expect(error?.message).toBe('mock network error');
  });

  test('triggerFailure() is a no-op before connect() (nothing to fail)', () => {
    const { session, delegates } = makeSession();

    session.triggerFailure();

    expect(session.state).toBe(CloudXR.SessionState.Initialized);
    expect(delegates.onStreamStopped).not.toHaveBeenCalled();
  });

  test('a blocking stream test that fails blocks connect and reports onStreamStopped(error)', () => {
    const { session, delegates } = makeSession({
      streamTest: { durationSeconds: 0, mode: 'block' },
    });
    session.connectWait(0);
    session.setNetworkQuality(CloudXR.QualityScore.Unsustainable);

    session.connect();
    expect(delegates.onStreamTestStarted).toHaveBeenCalledTimes(1);

    jest.advanceTimersByTime(0);

    expect(delegates.onStreamTestStopped).toHaveBeenCalledTimes(1);
    const [result] = delegates.onStreamTestStopped.mock.calls[0];
    expect(result.passed).toBe(false);
    expect(session.state).toBe(CloudXR.SessionState.Error);
    expect(delegates.onStreamStarted).not.toHaveBeenCalled();
    expect(delegates.onStreamStopped).toHaveBeenCalledTimes(1);
  });

  test('a passing (warn-mode) stream test still connects normally', () => {
    const { session, delegates } = makeSession({
      streamTest: { durationSeconds: 0, mode: 'warn' },
    });
    session.connectWait(0);
    session.setNetworkQuality(CloudXR.QualityScore.Excellent);

    session.connect();
    jest.runOnlyPendingTimers(); // stream test window
    jest.runOnlyPendingTimers(); // chained connect delay, scheduled from the timer above

    expect(delegates.onStreamTestStopped).toHaveBeenCalledTimes(1);
    expect(delegates.onStreamTestStopped.mock.calls[0][0].passed).toBe(true);
    expect(session.state).toBe(CloudXR.SessionState.Connected);
    expect(delegates.onStreamStarted).toHaveBeenCalledTimes(1);
  });

  test('render() with NullWebGLContext does no GL work but still reports frame metrics', () => {
    const { session, delegates } = makeSession({ gl: NullWebGLContext });
    session.connectWait(0);
    session.connect();
    jest.advanceTimersByTime(0);

    const frame = { getViewerPose: () => ({ views: [] }) } as unknown as XRFrame;
    const layer = {} as XRWebGLLayer; // never touched: no gl/layer calls happen in this mode

    expect(() => session.render(0, frame, layer)).not.toThrow();

    expect(delegates.onMetrics).toHaveBeenCalledWith(
      expect.objectContaining({ [CloudXR.MetricsName.StreamingFrameCount]: 1 }),
      CloudXR.MetricsCadence.PerFrame
    );
  });
});
