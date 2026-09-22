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
 * MockCloudXR - a `CloudXR.Session` stand-in for manual/visual testing of the WebXR client
 * without a real CloudXR server.
 *
 * Drives `CloudXR.SessionDelegates` through a plausible lifecycle (connecting -> connected,
 * periodic onLog/onMetrics, onStreamStopped on disconnect) and, in place of decoding a real
 * video stream, renders a small three.js scene into each eye's viewport of the XRWebGLLayer
 * handed to {@link MockCloudXR.render}.
 */

import * as CloudXR from '@nvidia/cloudxr';
import * as THREE from 'three';

const DEFAULT_CONNECT_DELAY_MS = 500;
const NETWORK_METRICS_INTERVAL_MS = 1000;

/** Per-quality-band sample ranges used to synthesize plausible {@link CloudXR.MetricsName} values. */
const NETWORK_QUALITY_PROFILES: Record<
  CloudXR.QualityScore,
  {
    streamingRateMbps: [number, number];
    availableBandwidthMbps: [number, number];
    rttMs: [number, number];
  }
> = {
  [CloudXR.QualityScore.NoData]: {
    streamingRateMbps: [0, 0],
    availableBandwidthMbps: [0, 0],
    rttMs: [0, 0],
  },
  [CloudXR.QualityScore.Excellent]: {
    streamingRateMbps: [150, 170],
    availableBandwidthMbps: [180, 200],
    rttMs: [5, 15],
  },
  [CloudXR.QualityScore.Good]: {
    streamingRateMbps: [80, 100],
    availableBandwidthMbps: [90, 110],
    rttMs: [30, 50],
  },
  [CloudXR.QualityScore.Degraded]: {
    streamingRateMbps: [40, 55],
    availableBandwidthMbps: [50, 65],
    rttMs: [100, 150],
  },
  [CloudXR.QualityScore.Unsustainable]: {
    streamingRateMbps: [10, 20],
    availableBandwidthMbps: [20, 30],
    rttMs: [250, 300],
  },
};

function randomInRange([min, max]: [number, number]): number {
  return min + Math.random() * (max - min);
}

interface MockScene {
  scene: THREE.Scene;
  /** Poses every animated object for a given scene time; see {@link MockCloudXR.setSceneTime}. */
  animate(timeSeconds: number): void;
}

/** Average standing eye height (m); matches a 'local' reference space, whose origin is at the
 * headset rather than the floor, so the scene reads correctly whether or not floor tracking
 * ('local-floor') is available. */
const SCENE_ORIGIN_Y = 1.6;

function buildMockScene(): MockScene {
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0x202030);

  const hemiLight = new THREE.HemisphereLight(0xffffff, 0x444444, 2);
  scene.add(hemiLight);
  const dirLight = new THREE.DirectionalLight(0xffffff, 1.5);
  dirLight.position.set(1, 2, 1);
  scene.add(dirLight);

  const contents = new THREE.Group();
  contents.position.y = SCENE_ORIGIN_Y;
  scene.add(contents);

  const floor = new THREE.Mesh(
    new THREE.PlaneGeometry(10, 10),
    new THREE.MeshStandardMaterial({ color: 0x3a3a4a })
  );
  floor.rotation.x = -Math.PI / 2;
  floor.position.y = -SCENE_ORIGIN_Y;
  contents.add(floor);

  const cube = new THREE.Mesh(
    new THREE.BoxGeometry(0.3, 0.3, 0.3),
    new THREE.MeshStandardMaterial({ color: 0x76b900 })
  );
  cube.position.set(0, 0, -1.5);
  contents.add(cube);

  const sphere = new THREE.Mesh(
    new THREE.SphereGeometry(0.15, 24, 16),
    new THREE.MeshStandardMaterial({ color: 0xff6b35 })
  );
  contents.add(sphere);

  const torus = new THREE.Mesh(
    new THREE.TorusGeometry(0.2, 0.06, 12, 24),
    new THREE.MeshStandardMaterial({ color: 0x3d8bfd })
  );
  torus.position.set(-0.6, 0.2, -1.8);
  contents.add(torus);

  const pillar = new THREE.Mesh(
    new THREE.CylinderGeometry(0.08, 0.08, 0.8, 16),
    new THREE.MeshStandardMaterial({ color: 0xcccccc })
  );
  pillar.position.set(0.6, -0.6, -1.6);
  contents.add(pillar);

  function animate(timeSeconds: number): void {
    cube.rotation.y = timeSeconds;
    cube.rotation.x = timeSeconds * 0.4;
    const orbitRadius = 0.7;
    sphere.position.set(
      Math.cos(timeSeconds * 0.5) * orbitRadius,
      0.1,
      -1.5 + Math.sin(timeSeconds * 0.5) * orbitRadius
    );
    torus.rotation.z = timeSeconds * 0.6;
  }

  return { scene, animate };
}

/**
 * Implements `CloudXR.Session` by rendering a mock three.js scene instead of decoded video.
 * Construct via {@link createMockCloudXRSession} rather than directly.
 */
export class MockCloudXR implements CloudXR.Session {
  private sessionState: CloudXR.SessionState = CloudXR.SessionState.Initialized;
  private sessionMicState: CloudXR.MicState = CloudXR.MicState.UNINITIALIZED;
  // Indexed-access type rather than naming CloudXR.MessageChannel directly: the SDK's shipped
  // .d.ts re-exports that type from a MessageChannel.d.ts file missing from the npm package.
  readonly availableMessageChannels: CloudXR.Session['availableMessageChannels'] = [];

  private connectTimer: ReturnType<typeof setTimeout> | null = null;
  private streamTestTimer: ReturnType<typeof setTimeout> | null = null;
  private networkMetricsTimer: ReturnType<typeof setInterval> | null = null;
  private frameCount = 0;
  private lastRenderTimestamp: DOMHighResTimeStamp | null = null;

  private connectDelayMs = DEFAULT_CONNECT_DELAY_MS;
  private networkQuality: CloudXR.QualityScore = CloudXR.QualityScore.Excellent;

  // Scene time is explicit rather than timestamp-driven, so the render is static/reproducible
  // by default; see MockCloudXR.setSceneTime / MockCloudXRController.setSceneTime.
  private sceneTime = 0;

  private readonly scene: THREE.Scene;
  private readonly sceneAnimate: (timeSeconds: number) => void;
  private readonly camera = new THREE.PerspectiveCamera();
  private renderer: THREE.WebGLRenderer | null = null;

  constructor(
    private readonly options: CloudXR.SessionOptions,
    private readonly delegates: CloudXR.SessionDelegates
  ) {
    const built = buildMockScene();
    this.scene = built.scene;
    this.sceneAnimate = built.animate;
  }

  get state(): CloudXR.SessionState {
    return this.sessionState;
  }

  get micState(): CloudXR.MicState {
    return this.sessionMicState;
  }

  connect(): void {
    if (
      this.sessionState !== CloudXR.SessionState.Initialized &&
      this.sessionState !== CloudXR.SessionState.Disconnected
    ) {
      throw new Error(`MockCloudXR.connect() called while in state ${this.sessionState}`);
    }
    this.sessionState = CloudXR.SessionState.Connecting;
    this.log(
      CloudXR.LogLevel.Info,
      `Mock connecting to ${this.options.serverAddress}:${this.options.serverPort} ` +
        `(codec=${this.options.codec ?? 'auto'}, perEye=${this.options.perEyeWidth}x${this.options.perEyeHeight})`
    );

    const streamTest = this.options.streamTest;
    if (streamTest && streamTest.mode !== 'off') {
      this.delegates.onStreamTestStarted?.();
      this.log(CloudXR.LogLevel.Info, `Mock stream test running (${streamTest.durationSeconds}s)`);
      this.streamTestTimer = setTimeout(() => {
        this.streamTestTimer = null;
        const result = this.buildStreamTestResult();
        this.delegates.onStreamTestStopped?.(result);
        if (streamTest.mode === 'block' && !result.passed) {
          this.log(CloudXR.LogLevel.Error, 'Mock stream test failed; blocking connect');
          this.triggerFailure({
            name: 'StreamingError',
            message: 'Mock stream test did not pass (blocking mode)',
          });
          return;
        }
        this.finishConnecting();
      }, streamTest.durationSeconds * 1000);
      return;
    }

    this.finishConnecting();
  }

  private finishConnecting(): void {
    this.connectTimer = setTimeout(() => {
      this.connectTimer = null;
      this.sessionState = CloudXR.SessionState.Connected;
      this.log(CloudXR.LogLevel.Info, 'Mock stream started');
      this.delegates.onStreamStarted?.();
      this.networkMetricsTimer = setInterval(
        () => this.emitNetworkMetrics(),
        NETWORK_METRICS_INTERVAL_MS
      );
    }, this.connectDelayMs);
  }

  private buildStreamTestResult(): CloudXR.StreamTestResult {
    const profile = NETWORK_QUALITY_PROFILES[this.networkQuality];
    const passed = this.networkQuality >= CloudXR.QualityScore.Degraded;
    return {
      passed,
      latencyScore: this.networkQuality,
      jitterScore: this.networkQuality,
      bandwidthScore: this.networkQuality,
      devicePerformanceScore: this.networkQuality,
      rttMs: randomInRange(profile.rttMs),
      serverFps: passed ? 90 : 30,
    };
  }

  disconnect(): void {
    if (
      this.sessionState === CloudXR.SessionState.Initialized ||
      this.sessionState === CloudXR.SessionState.Disconnected
    ) {
      return;
    }
    if (this.connectTimer !== null) {
      clearTimeout(this.connectTimer);
      this.connectTimer = null;
    }
    if (this.streamTestTimer !== null) {
      clearTimeout(this.streamTestTimer);
      this.streamTestTimer = null;
    }
    if (this.networkMetricsTimer !== null) {
      clearInterval(this.networkMetricsTimer);
      this.networkMetricsTimer = null;
    }
    this.sessionState = CloudXR.SessionState.Disconnecting;
    this.log(CloudXR.LogLevel.Info, 'Mock disconnecting');
    this.sessionState = CloudXR.SessionState.Disconnected;
    this.delegates.onStreamStopped?.(undefined);
  }

  sendTrackingStateToServer(timestamp: DOMHighResTimeStamp, frame: XRFrame): boolean {
    if (this.sessionState === CloudXR.SessionState.Connecting) {
      return false;
    }
    if (this.sessionState !== CloudXR.SessionState.Connected) {
      throw new Error(
        `MockCloudXR.sendTrackingStateToServer() called while in state ${this.sessionState}`
      );
    }
    const pose = frame.getViewerPose(this.options.referenceSpace);
    this.delegates.onMetrics?.(
      { [CloudXR.MetricsName.PoseSendFramerate]: this.estimateFps(timestamp) },
      CloudXR.MetricsCadence.PerRender
    );
    return pose !== null;
  }

  render(timestamp: DOMHighResTimeStamp, frame: XRFrame, layer: XRWebGLLayer): void {
    if (this.sessionState !== CloudXR.SessionState.Connected) {
      return;
    }
    const pose = frame.getViewerPose(this.options.referenceSpace);
    if (!pose) {
      return;
    }

    const gl = this.options.gl;
    const renderer = this.ensureRenderer(gl);
    this.sceneAnimate(this.sceneTime);

    this.delegates.onWebGLStateChangeBegin?.();
    gl.bindFramebuffer(gl.FRAMEBUFFER, layer.framebuffer);
    for (const view of pose.views) {
      const viewport = layer.getViewport(view);
      if (!viewport) {
        continue;
      }
      renderer.setViewport(viewport.x, viewport.y, viewport.width, viewport.height);
      renderer.setScissor(viewport.x, viewport.y, viewport.width, viewport.height);
      renderer.setScissorTest(true);
      this.camera.matrix.fromArray(view.transform.matrix);
      this.camera.matrix.decompose(this.camera.position, this.camera.quaternion, this.camera.scale);
      this.camera.projectionMatrix.fromArray(view.projectionMatrix);
      this.camera.projectionMatrixInverse.copy(this.camera.projectionMatrix).invert();
      renderer.render(this.scene, this.camera);
    }
    // The caller (CloudXRComponent / the demo harness) owns the gl context and expects its
    // own cached state back; three.js's WebGLRenderer caches gl state internally, so hand
    // it back with a clean slate rather than leaving our bindings live.
    renderer.state.reset();
    this.delegates.onWebGLStateChangeEnd?.();

    this.frameCount++;
    this.delegates.onMetrics?.(
      {
        [CloudXR.MetricsName.StreamingFramerate]: this.estimateFps(timestamp),
        [CloudXR.MetricsName.StreamingFrameCount]: this.frameCount,
      },
      CloudXR.MetricsCadence.PerFrame
    );
  }

  sendServerMessage(): void {
    throw new Error('MockCloudXR does not support sendServerMessage(); use a real session');
  }

  setMicEnabled(enabled: boolean): boolean {
    if (this.sessionState !== CloudXR.SessionState.Connected) {
      return false;
    }
    this.sessionMicState = enabled ? CloudXR.MicState.STARTED : CloudXR.MicState.STOPPED;
    this.delegates.onMicStateUpdate?.(this.sessionMicState);
    return true;
  }

  // --- Mock controls (not part of CloudXR.Session; used by MockCloudXRController) ---

  /** Sets how long the *next* connect() takes to reach Connected. Does not affect a connect() already in flight. */
  connectWait(ms: number): void {
    this.connectDelayMs = ms;
  }

  /** Changes the quality band used to synthesize network metrics and stream-test results. */
  setNetworkQuality(quality: CloudXR.QualityScore): void {
    this.networkQuality = quality;
  }

  /**
   * Sets the scene's animation time (seconds). The scene is static between calls: render() poses
   * animated objects from this value rather than the real render timestamp, so a given scene time
   * always renders the same frame.
   */
  setSceneTime(seconds: number): void {
    this.sceneTime = seconds;
  }

  /** Delivers `data` through `onServerMessageReceived`, as if the server had sent it. */
  sendFakeServerMessage(data: Uint8Array): void {
    this.delegates.onServerMessageReceived?.(data);
  }

  /**
   * Immediately fails the session, as a dropped connection or server-side error would.
   * No-op outside Connecting/Connected (mirrors real SDK behavior: there is nothing to fail).
   */
  triggerFailure(
    error: CloudXR.StreamingError = { name: 'StreamingError', message: 'Mock-triggered failure' }
  ): void {
    if (
      this.sessionState !== CloudXR.SessionState.Connecting &&
      this.sessionState !== CloudXR.SessionState.Connected
    ) {
      return;
    }
    if (this.connectTimer !== null) {
      clearTimeout(this.connectTimer);
      this.connectTimer = null;
    }
    if (this.streamTestTimer !== null) {
      clearTimeout(this.streamTestTimer);
      this.streamTestTimer = null;
    }
    if (this.networkMetricsTimer !== null) {
      clearInterval(this.networkMetricsTimer);
      this.networkMetricsTimer = null;
    }
    this.sessionState = CloudXR.SessionState.Error;
    this.log(CloudXR.LogLevel.Error, `Mock failure: ${error.message}`);
    this.delegates.onStreamStopped?.(error);
  }

  private ensureRenderer(gl: WebGL2RenderingContext): THREE.WebGLRenderer {
    if (!this.renderer) {
      this.renderer = new THREE.WebGLRenderer({
        context: gl,
        canvas: gl.canvas as HTMLCanvasElement,
      });
      this.renderer.autoClear = false;
    }
    return this.renderer;
  }

  private log(level: CloudXR.LogLevel, message: string): void {
    this.delegates.onLog?.([{ timestamp: performance.now(), level, message }]);
  }

  private emitNetworkMetrics(): void {
    const profile = NETWORK_QUALITY_PROFILES[this.networkQuality];
    this.delegates.onMetrics?.(
      {
        [CloudXR.MetricsName.NetworkStreamingRateMbps]: randomInRange(profile.streamingRateMbps),
        [CloudXR.MetricsName.NetworkAvailableBandwidthMbps]: randomInRange(
          profile.availableBandwidthMbps
        ),
        [CloudXR.MetricsName.NetworkRttMs]: randomInRange(profile.rttMs),
        [CloudXR.MetricsName.SessionQuality]: this.networkQuality,
      },
      CloudXR.MetricsCadence.PerNetwork
    );
  }

  private estimateFps(timestamp: DOMHighResTimeStamp): number {
    const fps =
      this.lastRenderTimestamp !== null && timestamp > this.lastRenderTimestamp
        ? 1000 / (timestamp - this.lastRenderTimestamp)
        : 0;
    this.lastRenderTimestamp = timestamp;
    return fps;
  }
}

/** Creates a {@link MockCloudXR} session; drop-in replacement for `CloudXR.createSession`. */
export function createMockCloudXRSession(
  options: CloudXR.SessionOptions,
  delegates: CloudXR.SessionDelegates = {}
): MockCloudXR {
  return new MockCloudXR(options, delegates);
}

/**
 * Thin wrapper exposing {@link MockCloudXR}'s mock-only controls under names meant to read well
 * from a devtools console (e.g. `mockCloudXR.triggerFailure()`, `mockCloudXR.connectWait(3000)`).
 * The mock demo page assigns one of these to `window.mockCloudXR`; see MockCloudXRTests.ts.
 */
export class MockCloudXRController {
  constructor(private readonly mock: MockCloudXR) {}

  /** Delays the *next* connect() by `ms` before it reaches Connected. */
  connectWait(ms: number): void {
    this.mock.connectWait(ms);
  }

  /** Fails the session right now, as a dropped connection or server error would. */
  triggerFailure(message?: string): void {
    this.mock.triggerFailure(message ? { name: 'StreamingError', message } : undefined);
  }

  /** Switches the simulated network/stream-test quality band. */
  setNetworkQuality(quality: CloudXR.QualityScore): void {
    this.mock.setNetworkQuality(quality);
  }

  /** Sets the scene's animation time (seconds); the render is static until this is called again. */
  setSceneTime(seconds: number): void {
    this.mock.setSceneTime(seconds);
  }

  /** Delivers a fake inbound server message. */
  sendFakeServerMessage(data: Uint8Array): void {
    this.mock.sendFakeServerMessage(data);
  }
}
