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
 * CloudXRComponentTest - minimal harness mounting the real CloudXRComponent (not App.tsx's full
 * production UI: no CloudXR2DUI/CloudXR3DUI, settings panel, or recorder) inside a bare
 * Canvas/XR tree, against MockCloudXR via the build-time '@nvidia/cloudxr' alias (see
 * cloudxr-mock-alias.ts / webpack.component-mock.js). Exercises the real CloudXRComponent.tsx
 * code path - unlike MockCloudXRTests.ts, which hand-drives MockCloudXR directly with no React
 * involved at all.
 *
 * Click the button (or press "S") to run a scripted three-step sequence:
 *   1. Start normally, then close cleanly - expect zero error events.
 *   2. Start with a 2s connect delay, trigger a non-retryable failure 1s in (still Connecting).
 *   3. Start with no connect delay, wait 2s (now Connected), trigger a retryable failure.
 * Non-retryable/retryable here means the server-disconnect error-code range CloudXRComponent's
 * planned retry logic will check (0xC0F223xx = non-retryable); no retry exists yet, so today
 * every step ends the session the same way - this script exists to make that behavior (and the
 * future fix) easy to eyeball and to give the fix a ready-made manual repro.
 */

import * as CloudXR from '@nvidia/cloudxr';
import { Canvas } from '@react-three/fiber';
import { createXRStore, noEvents, PointerEvents, XR, XROrigin } from '@react-three/xr';
import { useCallback, useEffect, useRef, useState } from 'react';
import ReactDOM from 'react-dom/client';

import { loadIWERIfNeeded } from '@helpers/LoadIWER';
import CloudXRComponent from '@helpers/react/CloudXRComponent';
import type { CloudXRConfig } from '@helpers/utils';

import type { MockCloudXR } from './MockCloudXR';

const NON_RETRYABLE_CODE = 0xc0f22300; // server-disconnect range
const RETRYABLE_CODE = 0xc0f22204; // NetworkInterrupted

function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

async function waitUntil(predicate: () => boolean, timeoutMs: number): Promise<boolean> {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (predicate()) {
      return true;
    }
    await sleep(50);
  }
  return predicate();
}

const config: CloudXRConfig = {
  serverIP: 'mock',
  port: 0,
  useSecureConnection: false,
  perEyeWidth: 1024,
  perEyeHeight: 1024,
  deviceFrameRate: 72,
  maxStreamingBitrateMbps: 100,
  immersiveMode: 'vr',
  serverType: 'mock',
  proxyUrl: '',
  referenceSpaceType: 'local-floor',
};

// IWER is loaded manually below (same as MockCloudXRTests.ts), so disable the store's own
// emulation; controller/hand models are skipped since this harness never renders them.
const store = createXRStore({
  emulate: false,
  hand: { model: false },
  controller: { model: false },
  offerSession: false,
});

function appendLog(message: string): void {
  const logEl = document.getElementById('log');
  if (!logEl) {
    return;
  }
  const line = document.createElement('div');
  line.textContent = message;
  logEl.appendChild(line);
  logEl.scrollTop = logEl.scrollHeight;
}

// Mutable script state, module-level rather than React state: Scene/App never need to re-render
// on these changing, and the step functions below need to read/write them outside any component.
let activeSession: MockCloudXR | null = null;
let pendingConnectWaitMs: number | null = null;
let hadError = false;

function Scene() {
  return (
    <XR store={store}>
      <XROrigin />
      <CloudXRComponent
        config={config}
        applicationName="CloudXRComponentTest"
        onStatusChange={(isConnected, status) =>
          appendLog(`[status] connected=${isConnected} ${status}`)
        }
        onError={error => {
          hadError = true;
          appendLog(`[error] ${error}`);
        }}
        onExitImmersiveXR={() => {
          appendLog('[event] onExitImmersiveXR');
          // Mirrors App.tsx's handleDisconnect: exiting immersive XR means ending the WebXR
          // session, which is what actually drives CloudXRComponent's own cleanup/disconnect.
          store.getState().session?.end();
        }}
        onSessionReady={session => {
          activeSession = session as MockCloudXR | null;
          if (activeSession && pendingConnectWaitMs !== null) {
            activeSession.connectWait(pendingConnectWaitMs);
            pendingConnectWaitMs = null;
          }
          appendLog(`[event] onSessionReady ${session ? 'session' : 'null'}`);
        }}
        onStreamTestStarted={() => appendLog('[event] onStreamTestStarted')}
        onStreamTestStopped={result =>
          appendLog(`[event] onStreamTestStopped passed=${result.passed}`)
        }
      />
    </XR>
  );
}

/** Sets the next session's connect delay (applied in onSessionReady, see above), then enters VR. */
async function startSession(connectWaitMs: number | null): Promise<void> {
  pendingConnectWaitMs = connectWaitMs;
  const { supportsImmersive } = await loadIWERIfNeeded();
  if (!supportsImmersive) {
    appendLog('[error] No immersive WebXR support and IWER emulation failed to load.');
    return;
  }
  try {
    await store.enterVR();
  } catch (error) {
    appendLog(
      `[error] Failed to start XR session: ${error instanceof Error ? error.message : String(error)}`
    );
  }
}

async function runStep1(): Promise<void> {
  appendLog('=== Step 1: start, then close cleanly - expect no errors ===');
  hadError = false;
  await startSession(null);
  await waitUntil(() => activeSession?.state === CloudXR.SessionState.Connected, 3000);
  store.getState().session?.end();
  await sleep(500);
  appendLog(hadError ? '[step1] FAIL: saw an error event' : '[step1] PASS: no errors');
}

async function runStep2(): Promise<void> {
  appendLog('=== Step 2: fail while still connecting (non-retryable) ===');
  await startSession(2000);
  await sleep(1000);
  activeSession?.triggerFailure({
    name: 'StreamingError',
    message: 'Mock non-retryable failure (server-disconnect range)',
    code: NON_RETRYABLE_CODE,
  });
  await sleep(500);
}

async function runStep3(): Promise<void> {
  appendLog('=== Step 3: fail once connected (retryable) ===');
  await startSession(0);
  await sleep(2000);
  activeSession?.triggerFailure({
    name: 'StreamingError',
    message: 'Mock retryable failure (network interrupted)',
    code: RETRYABLE_CODE,
  });
  await sleep(500);
}

function App() {
  const [running, setRunning] = useState(false);
  const runningRef = useRef(false);

  const runSequence = useCallback(async () => {
    if (runningRef.current) {
      return;
    }
    runningRef.current = true;
    setRunning(true);
    try {
      await runStep1();
      await runStep2();
      await runStep3();
      appendLog('=== Test sequence complete ===');
    } finally {
      runningRef.current = false;
      setRunning(false);
    }
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === 's') {
        void runSequence();
      }
    };
    window.addEventListener('keydown', onKeyDown);
    return () => window.removeEventListener('keydown', onKeyDown);
  }, [runSequence]);

  return (
    <>
      <div id="panel">
        {!running && (
          <button id="startButton" type="button" onClick={() => void runSequence()}>
            Start CloudXRComponent (Mock) [S]
          </button>
        )}
        <div id="log" />
      </div>
      <Canvas events={noEvents} style={{ position: 'fixed', inset: 0, zIndex: -1 }}>
        <PointerEvents batchEvents={false} />
        <Scene />
      </Canvas>
    </>
  );
}

const container = document.getElementById('root');
if (container) {
  ReactDOM.createRoot(container).render(<App />);
} else {
  console.error('CloudXRComponentTest: #root container not found');
}
