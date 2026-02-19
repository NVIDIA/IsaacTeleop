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
 * CloudXRComponent.tsx - CloudXR WebXR Integration Component
 *
 * This component handles the core CloudXR streaming functionality and WebXR integration.
 * It manages:
 * - CloudXR session lifecycle (creation, connection, disconnection, cleanup)
 * - WebXR session event handling (sessionstart, sessionend)
 * - WebGL state management and render target preservation
 * - Frame-by-frame rendering loop with pose tracking and stream rendering
 * - Server configuration and connection parameters
 * - Status reporting back to parent components
 *
 * The component accepts configuration via props and communicates status changes
 * and disconnect requests through callback props. It integrates with Three.js
 * and React Three Fiber for WebXR rendering while preserving WebGL state
 * for CloudXR's custom rendering pipeline.
 */

import { MetricsTracker } from '@helpers/Metrics';
import { getConnectionConfig, ConnectionConfiguration, CloudXRConfig } from '@helpers/utils';
import { bindGL } from '@helpers/WebGLStateBinding';
import * as CloudXR from '@nvidia/cloudxr';
import { useThree, useFrame } from '@react-three/fiber';
import { useXR } from '@react-three/xr';
import { useRef, useEffect } from 'react';
import type { WebGLRenderer } from 'three';

/**
 * Props for the CloudXRComponent.
 */
interface CloudXRComponentProps {
  /** CloudXR configuration including server address, resolution, and XR settings. */
  config: CloudXRConfig;

  /** Application name used for telemetry. */
  applicationName: string;

  /** Callback fired when connection status changes. Receives connection state and human-readable status message. */
  onStatusChange?: (isConnected: boolean, status: string) => void;

  /** Callback fired when an error occurs. Receives error message string. */
  onError?: (error: string) => void;

  /** Callback fired when CloudXR session is created or destroyed. Receives session instance or null. */
  onSessionReady?: (session: CloudXR.Session | null) => void;

  /** Callback fired with the resolved server address after proxy configuration is applied. */
  onServerAddress?: (address: string) => void;

  /** Callback fired with render performance metrics. Receives rolling average of render FPS. */
  onRenderPerformanceMetrics?: (renderFps: number) => void;

  /** Callback fired with streaming performance metrics. Receives rolling averages of streaming FPS and pose-to-render latency (ms). */
  onStreamingPerformanceMetrics?: (streamingFps: number, poseToRenderMs: number) => void;

  /**
   * Settings for the performance metrics reported via onRenderPerformanceMetrics and onStreamingPerformanceMetrics callbacks.
   * Each window size controls how many samples are averaged before reporting.
   */
  metricsSettings?: {
    /** Window size for render FPS rolling average. Default: 100 */
    renderFpsWindow?: number;
    /** Window size for streaming FPS rolling average. Default: 20 */
    streamingFpsWindow?: number;
    /** Window size for pose-to-render latency rolling average. Default: 20 */
    poseToRenderWindow?: number;
  };
}

// React component that integrates CloudXR with Three.js/WebXR
// This component handles the CloudXR session lifecycle and render loop
export default function CloudXRComponent({
  config,
  applicationName,
  onStatusChange,
  onError,
  onSessionReady,
  onServerAddress,
  onRenderPerformanceMetrics,
  onStreamingPerformanceMetrics,
  metricsSettings = {},
}: CloudXRComponentProps) {
  const threeRenderer: WebGLRenderer = useThree().gl;
  const { session } = useXR();
  // React reference to the CloudXR session that persists across re-renders.
  const cxrSessionRef = useRef<CloudXR.Session | null>(null);

  // Metrics trackers for averaging performance metrics
  // Use prop values if provided, otherwise use defaults
  const renderFpsTrackerRef = useRef<MetricsTracker>(
    new MetricsTracker(metricsSettings.renderFpsWindow ?? 100)
  );
  const streamingFpsTrackerRef = useRef<MetricsTracker>(
    new MetricsTracker(metricsSettings.streamingFpsWindow ?? 20)
  );
  const poseToRenderTrackerRef = useRef<MetricsTracker>(
    new MetricsTracker(metricsSettings.poseToRenderWindow ?? 20)
  );

  // Disable Three.js so it doesn't clear the framebuffer after CloudXR renders.
  threeRenderer.autoClear = false;

  // Access Three.js WebXRManager and WebGL context.
  const gl: WebGL2RenderingContext = threeRenderer.getContext() as WebGL2RenderingContext;

  const trackedGL = bindGL(gl);

  // Set up event listeners in useEffect to add them only once
  useEffect(() => {
    const webXRManager = threeRenderer.xr;

    if (webXRManager) {
      const handleSessionStart = async () => {
        // Explicitly request the desired reference space from the XRSession to avoid
        // inheriting a default 'local-floor' space that could stack with UI offsets.
        let referenceSpace: XRReferenceSpace | null = null;
        try {
          const xrSession: XRSession | null = (webXRManager as any).getSession
            ? (webXRManager as any).getSession()
            : null;
          if (xrSession) {
            if (config.referenceSpaceType === 'auto') {
              const fallbacks: XRReferenceSpaceType[] = [
                'local-floor',
                'local',
                'viewer',
                'unbounded',
              ];
              for (const t of fallbacks) {
                try {
                  referenceSpace = await xrSession.requestReferenceSpace(t);
                  if (referenceSpace) break;
                } catch (_) {}
              }
            } else {
              try {
                referenceSpace = await xrSession.requestReferenceSpace(
                  config.referenceSpaceType as XRReferenceSpaceType
                );
              } catch (error) {
                console.error(
                  `Failed to request reference space '${config.referenceSpaceType}':`,
                  error
                );
              }
            }
          }
        } catch (error) {
          console.error('Failed to request XR reference space:', error);
          referenceSpace = null;
        }

        if (!referenceSpace) {
          // As a last resort, fall back to WebXRManager's current reference space
          referenceSpace = webXRManager.getReferenceSpace();
        }

        if (referenceSpace) {
          // Ensure that the session is not already created.
          if (cxrSessionRef.current) {
            console.error('CloudXR session already exists');
            return;
          }

          const glBinding = webXRManager.getBinding();
          if (!glBinding) {
            console.warn('No WebGL binding found');
          }

          // Apply proxy configuration logic
          let connectionConfig: ConnectionConfiguration;
          try {
            connectionConfig = getConnectionConfig(config.serverIP, config.port, config.proxyUrl);
            onServerAddress?.(connectionConfig.serverIP);
          } catch (error) {
            onStatusChange?.(false, 'Configuration Error');
            onError?.(`Proxy configuration failed: ${error}`);
            return;
          }

          // Apply XR offset if provided in config (meters)
          const offsetX = config.xrOffsetX || 0;
          const offsetY = config.xrOffsetY || 0;
          const offsetZ = config.xrOffsetZ || 0;
          if (offsetX !== 0 || offsetY !== 0 || offsetZ !== 0) {
            const offsetTransform = new XRRigidTransform(
              { x: offsetX, y: offsetY, z: offsetZ },
              { x: 0, y: 0, z: 0, w: 1 }
            );
            referenceSpace = referenceSpace.getOffsetReferenceSpace(offsetTransform);
          }

          // Fill in CloudXR session options.
          const cloudXROptions: CloudXR.SessionOptions = {
            serverAddress: connectionConfig.serverIP,
            serverPort: connectionConfig.port,
            useSecureConnection: connectionConfig.useSecureConnection,
            signalingResourcePath: connectionConfig.resourcePath,
            perEyeWidth: config.perEyeWidth,
            perEyeHeight: config.perEyeHeight,
            codec: config.codec,
            gl: gl,
            referenceSpace: referenceSpace,
            deviceFrameRate: config.deviceFrameRate,
            maxStreamingBitrateKbps: config.maxStreamingBitrateMbps * 1000, // Convert Mbps to Kbps
            enablePoseSmoothing: config.enablePoseSmoothing,
            posePredictionFactor: config.posePredictionFactor,
            enableTexSubImage2D: config.enableTexSubImage2D,
            useQuestColorWorkaround: config.useQuestColorWorkaround,
            mediaAddress: config.mediaAddress,
            mediaPort: config.mediaPort,
            glBinding: glBinding,
            telemetry: {
              enabled: true,
              appInfo: {
                version: '6.1.0',
                product: applicationName,
              },
            },
          };

          // Store the render target and key GL bindings to restore after CloudXR rendering
          const cloudXRDelegates: CloudXR.SessionDelegates = {
            onWebGLStateChangeBegin: () => {
              // Save the current render target before CloudXR changes state
              trackedGL.save();
            },
            onWebGLStateChangeEnd: () => {
              // Restore the tracked GL state to the state before CloudXR rendering.
              trackedGL.restore();
            },
            onStreamStarted: () => {
              console.debug('CloudXR stream started');
              onStatusChange?.(true, 'Connected');
            },
            onStreamStopped: (error?: CloudXR.StreamingError) => {
              if (error) {
                // Display user-friendly error message with error code if available
                const errorMsg = error.code
                  ? `${error.message} (Error code: 0x${error.code.toString(16).toUpperCase()})`
                  : error.message;

                console.error('Stream stopped with error:', errorMsg);
                onStatusChange?.(false, 'Error');
                onError?.(`CloudXR session stopped: ${errorMsg}`);

                // Log additional debug info if available
                if (error.reasonCode !== undefined) {
                  console.debug('Stop reason code:', error.reasonCode);
                }
              } else {
                console.debug('CloudXR session stopped');
                onStatusChange?.(false, 'Disconnected');
              }
              // Clear the session reference
              cxrSessionRef.current = null;
              onSessionReady?.(null);
            },
            onMetrics: (metrics: CloudXR.Metrics, cadence: CloudXR.MetricsCadence) => {
              // Handle render performance metrics (PerRender cadence)
              if (onRenderPerformanceMetrics && cadence === CloudXR.MetricsCadence.PerRender) {
                // Return the averaged metrics to the parent component
                const renderFps = metrics[CloudXR.MetricsName.RenderFramerate] ?? 0;
                onRenderPerformanceMetrics(renderFpsTrackerRef.current.add(renderFps));
              }

              // Handle streaming performance metrics (PerFrame cadence)
              if (onStreamingPerformanceMetrics && cadence === CloudXR.MetricsCadence.PerFrame) {
                const streamingFps = metrics[CloudXR.MetricsName.StreamingFramerate] ?? 0;
                const poseToRenderMs = metrics[CloudXR.MetricsName.PoseToRenderTime] ?? 0;

                // Return the averaged metrics to the parent component
                onStreamingPerformanceMetrics(
                  streamingFpsTrackerRef.current.add(streamingFps),
                  poseToRenderTrackerRef.current.add(poseToRenderMs)
                );
              }
            },
          };

          // Create the CloudXR session.
          let cxrSession: CloudXR.Session;
          try {
            cxrSession = CloudXR.createSession(cloudXROptions, cloudXRDelegates);
          } catch (error) {
            onStatusChange?.(false, 'Session Creation Failed');
            onError?.(`Failed to create CloudXR session: ${error}`);
            return;
          }

          // Store the session in the ref so it persists across re-renders
          cxrSessionRef.current = cxrSession;

          // Notify parent that session is ready
          onSessionReady?.(cxrSession);

          // Start session (synchronous call that initiates connection)
          try {
            cxrSession.connect();
            console.log('CloudXR session connect initiated');
            // Note: The session will transition to Connected state via the onStreamStarted callback
            // Use cxrSession.state to check if streaming has actually started
          } catch (error) {
            onStatusChange?.(false, 'Connection Failed');
            // Report error via callback
            onError?.('Failed to connect CloudXR session');
            // Clean up the failed session
            cxrSessionRef.current = null;
          }
        }
      };

      const handleSessionEnd = () => {
        if (cxrSessionRef.current) {
          cxrSessionRef.current.disconnect();
          cxrSessionRef.current = null;
          onSessionReady?.(null);
        }
      };

      // Add start+end session event listeners to the WebXRManager.
      webXRManager.addEventListener('sessionstart', handleSessionStart);
      webXRManager.addEventListener('sessionend', handleSessionEnd);

      // Cleanup function to remove listeners
      return () => {
        webXRManager.removeEventListener('sessionstart', handleSessionStart);
        webXRManager.removeEventListener('sessionend', handleSessionEnd);
      };
    }
  }, [threeRenderer, config]); // Re-register handlers when renderer or config changes

  // Custom render loop - runs every frame
  useFrame((state, delta) => {
    const webXRManager = threeRenderer.xr;

    if (webXRManager.isPresenting && session) {
      // Access the current WebXR XRFrame
      const xrFrame = state.gl.xr.getFrame();
      if (xrFrame) {
        // Get THREE WebXRManager from the the useFrame state.
        const webXRManager = state.gl.xr;

        if (!cxrSessionRef || !cxrSessionRef.current) {
          console.debug('Skipping frame, no session yet');
          // Clear the framebuffer as we've set autoClear to false.
          threeRenderer.clear();
          return;
        }

        // Get session from reference.
        const cxrSession: CloudXR.Session = cxrSessionRef.current;

        // If the CloudXR session is not connected, skip the frame.
        if (cxrSession.state !== CloudXR.SessionState.Connected) {
          console.debug('Skipping frame, session not connected, state:', cxrSession.state);
          // Clear the framebuffer as we've set autoClear to false.
          threeRenderer.clear();
          return;
        }

        // Get timestamp from useFrame state and convert to milliseconds.
        const timestamp: DOMHighResTimeStamp = state.clock.elapsedTime * 1000;

        try {
          // Send the tracking state (including viewer pose and hand/controller data) to the server, this will trigger server-side rendering for frame.
          cxrSession.sendTrackingStateToServer(timestamp, xrFrame);

          // Get the WebXR layer from THREE WebXRManager.
          let layer: XRWebGLLayer = webXRManager.getBaseLayer() as XRWebGLLayer;

          // Render the current streamed CloudXR frame (not the frame that was just sent to the server).
          cxrSession.render(timestamp, xrFrame, layer);
        } catch (error) {
          // Handle deferred exceptions from callbacks or render errors
          const errorMessage = error instanceof Error ? error.message : String(error);
          console.error('CloudXR render loop error:', error);
          // Disconnect session on error
          cxrSession.disconnect();
          onError?.(`CloudXR error: ${errorMessage}`);
        }
      }
    }
  }, -1000);

  return null;
}
