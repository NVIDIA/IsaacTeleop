// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { test, expect } from '@playwright/test';

// E2E coverage for the CloudXR web client streaming against a live runtime.
//
// The web client renders most of its UI inside the WebGL canvas via
// @react-three/uikit, which is not queryable as DOM. We therefore assert
// against the regular HTML elements managed by CloudXR2DUI in
// deps/cloudxr/webxr_client/src/index.html:
//   - #errorMessageText (status banner)
//   - #startButton (CONNECT button)
//
// IWER (loaded automatically when navigator.xr cannot satisfy
// isSessionSupported('immersive-vr'/'immersive-ar')) installs a mock XR device
// in headless Chromium so requestSession() resolves and the React XR store
// transitions into immersive-* mode.
//
// Important: #startButton flipping to "CONNECT (XR session active)" only
// proves IWER's mock session started — it fires before any traffic reaches
// the runtime. To prove an actual round-trip with the CloudXR runtime we
// observe the page-opened WebSocket directly via page.on('websocket') and
// require N inbound frames from the server end of the signaling channel.
//
// NOTE: the /sign_in WS is NOT a sustained channel. It carries the SDP
// answer + ICE candidates (typically 3-5 inbound frames) and then the
// server closes it cleanly. Video subsequently flows over WebRTC RTP /
// data channels, which are not visible to page.on('websocket'). So we set
// a low frame threshold (covers SDP + at least one ICE candidate) and
// treat a clean close after that as success.
const REQUIRED_RUNTIME_FRAMES = 3;

// Time to allow WebRTC to negotiate, decode, and render the first video
// frames into the WebGL canvas after signaling completes. Used both as the
// stability window and as the lead-in for the visual-evidence screenshot.
const POST_SIGNALING_RENDER_MS = 8_000;

test('cloudxr web client streams from runtime', async ({ page }) => {
  // Plain ws:// to the runtime: the page is served over http://, so
  // CloudXR2DUI.getDefaultConfiguration() picks useSecure=false and connects
  // to ws://<host>:49100/... directly. No TLS, no certs, no wss-proxy.
  const cxrHost = process.env.CXR_HOST ?? 'cloudxr-runtime';
  const cxrPort = process.env.CXR_PORT ?? '49100';
  const url = `/?serverIP=${cxrHost}&port=${cxrPort}`;

  // Match either ws:// or wss:// to the configured runtime host:port. The
  // SDK appends its own path (e.g. /signaling/...), so anchor on host:port.
  const cxrSocketUrl = new RegExp(`^wss?://${cxrHost}:${cxrPort}(/|$)`);

  // Latch state for the first runtime-bound WebSocket the page opens. Counter
  // is read inside error paths to surface partial-progress information when
  // the socket closes before reaching REQUIRED_RUNTIME_FRAMES.
  let runtimeFramesSeen = 0;
  let runtimeFramesResolve: ((url: string) => void) | undefined;
  let runtimeFramesReject: ((reason: Error) => void) | undefined;
  const runtimeFrames = new Promise<string>((resolve, reject) => {
    runtimeFramesResolve = resolve;
    runtimeFramesReject = reject;
  });

  page.on('websocket', ws => {
    if (!cxrSocketUrl.test(ws.url())) return;
    ws.on('framereceived', () => {
      runtimeFramesSeen += 1;
      if (runtimeFramesSeen >= REQUIRED_RUNTIME_FRAMES) runtimeFramesResolve?.(ws.url());
    });
    ws.on('socketerror', err => runtimeFramesReject?.(new Error(
      `WS error on ${ws.url()} after ${runtimeFramesSeen}/${REQUIRED_RUNTIME_FRAMES} frames: ${err}`,
    )));
    ws.on('close', () => runtimeFramesReject?.(new Error(
      `WS closed after ${runtimeFramesSeen}/${REQUIRED_RUNTIME_FRAMES} frames: ${ws.url()}`,
    )));
  });

  await page.goto(url);

  // Capabilities pass: confirms IWER injected a working navigator.xr and the
  // CloudXR JS SDK initialized successfully. Generous timeout covers the
  // unpkg.com IWER fetch on first load.
  await expect(page.locator('#errorMessageText')).toContainText(
    'CloudXR.js SDK is supported.',
    { timeout: 30_000 },
  );

  // The CONNECT button is enabled once the capability gate completes.
  const button = page.locator('#startButton');
  await expect(button).toBeEnabled({ timeout: 15_000 });
  await button.click();

  // Set by App.tsx when the @react-three/xr store enters immersive-vr/ar mode.
  // Necessary precondition (IWER session started), but not sufficient on its
  // own — the WS framereceived check below is what proves real connectivity.
  await expect(button).toHaveText('CONNECT (XR session active)', { timeout: 30_000 });

  // Real connectivity gate: REQUIRED_RUNTIME_FRAMES inbound frames means the
  // runtime accepted the upgrade and is sustaining traffic. Resolves on the
  // Nth frame; rejects on early close / socket error with a partial-progress
  // count so failures fail loudly instead of silently passing.
  const runtimeUrl = await Promise.race([
    runtimeFrames,
    new Promise<never>((_, reject) =>
      setTimeout(
        () => reject(new Error(
          `Only received ${runtimeFramesSeen}/${REQUIRED_RUNTIME_FRAMES} WebSocket frames `
          + `from ${cxrHost}:${cxrPort} within 30s`,
        )),
        30_000,
      ),
    ),
  ]);
  expect(runtimeUrl).toMatch(cxrSocketUrl);

  // Combined stability + render window: signaling has just closed cleanly,
  // and WebRTC needs time to negotiate, decode, and render the first video
  // frames into the WebGL canvas. The label staying as 'CONNECT (XR session
  // active)' through this window also confirms the XR store didn't tear
  // back to plain 'CONNECT' after a botched handshake.
  await page.waitForTimeout(POST_SIGNALING_RENDER_MS);
  await expect(button).toHaveText('CONNECT (XR session active)');

  // Switch IWER's primary input mode from controller to hand and animate
  // the right hand through a small stepped trajectory (translate + yaw).
  // Exercises the hand-tracking pose path through the XRDevice ->
  // XRSession -> @react-three/xr pipeline across multiple frames (a
  // single-step set could be missed by the WebRTC datachannel cadence),
  // and produces a visibly moving hand in the recorded video.webm.
  // Uses the public XRDevice API exposed by helpers/LoadIWER.ts on
  // window.xrDevice — no webxr_client source changes required.
  await page.evaluate(async () => {
    const device = (window as { xrDevice?: {
      controlMode: string;
      primaryInputMode: 'controller' | 'hand';
      hands: { right?: {
        position: { x: number; y: number; z: number; set: (x: number, y: number, z: number) => void };
        quaternion: { set: (x: number, y: number, z: number, w: number) => void };
      } };
      notifyStateChange?: () => void;
    } }).xrDevice;
    if (!device) return;
    device.controlMode = 'programmatic';
    device.primaryInputMode = 'hand';
    // Both hands are created in XRDevice's ctor and start with connected=true
    // (XRTrackedInput.js), so flipping primaryInputMode is enough to make
    // them show up in activeInputs/inputSources.
    const right = device.hands.right;
    if (!right) return;

    const sleep = (ms: number) => new Promise(r => setTimeout(r, ms));
    const STEPS = 10;
    const STEP_DELAY_MS = 50;       // ~20 Hz: well under runtime frame rate
    const dxPerStep = 0.02;         // total +0.20 m to the right
    const dyPerStep = 0.01;         // total +0.10 m up
    const dyawPerStep = 0.03;       // total +0.30 rad (~17°) yaw

    const x0 = right.position.x;
    const y0 = right.position.y;
    const z0 = right.position.z;

    for (let i = 1; i <= STEPS; i++) {
      right.position.set(x0 + dxPerStep * i, y0 + dyPerStep * i, z0);
      const half = (dyawPerStep * i) / 2;
      right.quaternion.set(0, Math.sin(half), 0, Math.cos(half));
      device.notifyStateChange?.();
      await sleep(STEP_DELAY_MS);
    }
  });

  // Visual confirmation: streamed scene with hand-tracking active and the
  // right hand visibly rotated. Always saved (alongside the auto
  // on-failure shot) so green runs also ship visual evidence in the
  // web-e2e-results CI artifact.
  await page.screenshot({ path: 'test-results/streaming.png', fullPage: false });
});
