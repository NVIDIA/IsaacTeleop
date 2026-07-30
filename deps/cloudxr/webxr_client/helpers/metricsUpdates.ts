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
 * Shapes for the metrics CloudXRComponent forwards to the app, one per SDK
 * MetricsCadence.
 *
 * The SDK delivers `onMetrics` as a partial `Record<MetricsName, number>`: a
 * single tick carries only the keys that were sampled on that path (the
 * send-begin and render-begin paths, for example, each emit their own PerRender
 * callback). Every field here is therefore optional, and consumers must merge
 * rather than replace — see `MetricsAccumulator` in metricsAccumulator.ts.
 */

/** Metrics delivered at {@link CloudXR.MetricsCadence.PerRender} (once per client render). */
export interface RenderMetricsUpdate {
  /** Client render rate, rolling average (FPS). */
  framerate?: number;
  /** Rate at which poses are sent upstream, rolling average (FPS). */
  sendFramerate?: number;
  /** Age of the XR pose at send time (ms). */
  xrPoseAgeMs?: number;
}

/** Metrics delivered at {@link CloudXR.MetricsCadence.PerFrame} (once per streamed video frame). */
export interface FrameMetricsUpdate {
  /** Streaming rate, rolling average (FPS). */
  framerate?: number;
  /** Monotonic count of streamed frames. */
  frameCount?: number;
  /** Pose-to-render latency, rolling average (ms). */
  poseToRenderTimeMs?: number;
  /** Time spent uploading the pose (ms). */
  poseUploadMs?: number;
  /** Time from pose send to frame received (ms). */
  poseToFrameReceivedMs?: number;
  /** Share of frames the compositor skipped (%). */
  compositorSkippedPercent?: number;
  /** Share of frames that arrived out of order (%). */
  outOfOrderPercent?: number;
  /** Share of frames whose pose did not match the rendered pixels (%). */
  mismatchedPercent?: number;
}

/** Metrics delivered at {@link CloudXR.MetricsCadence.PerNetwork} (network sampling cadence). */
export interface NetworkMetricsUpdate {
  /** Current streaming rate (Mbps). */
  streamingRateMbps?: number;
  /** Estimated available bandwidth (Mbps). */
  availableBandwidthMbps?: number;
  /** Round-trip time (ms). */
  rttMs?: number;
  /** Packet loss ratio. */
  packetLoss?: number;
  /** Average video decode time (ms). */
  avgDecodeTimeMs?: number;
  /** Composite network quality, a {@link CloudXR.QualityScore}. */
  qualityScore?: number;
  /** Bandwidth component of the quality score, a {@link CloudXR.QualityScore}. */
  bandwidthScore?: number;
  /** Loss component of the quality score, a {@link CloudXR.QualityScore}. */
  lossScore?: number;
  /** Latency component of the quality score, a {@link CloudXR.QualityScore}. */
  latencyScore?: number;
  /** Overall session quality 0-4, a {@link CloudXR.QualityScore}; drives the HUD indicator. */
  sessionQuality?: number;
}
