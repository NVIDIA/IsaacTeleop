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

interface CapabilityCheck {
  name: string;
  required: boolean;
  check: () => boolean | Promise<boolean>;
  message: string;
}

const capabilities: CapabilityCheck[] = [
  {
    name: 'WebGL2',
    required: true,
    check: () => {
      const canvas = document.createElement('canvas');
      const gl = canvas.getContext('webgl2');
      return gl !== null;
    },
    message: 'WebGL2 is required for rendering',
  },
  {
    name: 'WebXR',
    required: true,
    check: () => {
      return 'xr' in navigator;
    },
    message: 'WebXR is required for VR/AR functionality',
  },
  {
    name: 'RTCPeerConnection',
    required: true,
    check: () => {
      return 'RTCPeerConnection' in window;
    },
    message: 'RTCPeerConnection is required for WebRTC streaming',
  },
  {
    name: 'requestVideoFrameCallback',
    required: true,
    check: () => {
      const video = document.createElement('video');
      return typeof video.requestVideoFrameCallback === 'function';
    },
    message: 'HTMLVideoElement.requestVideoFrameCallback is required for video frame processing',
  },
  {
    name: 'Canvas.captureStream',
    required: true,
    check: () => {
      const canvas = document.createElement('canvas');
      return typeof canvas.captureStream === 'function';
    },
    message: 'Canvas.captureStream is required for video streaming',
  },
  {
    name: 'AV1 Codec Support',
    required: false,
    check: async () => {
      try {
        // Check if MediaCapabilities API is available
        if (!navigator.mediaCapabilities) {
          return false;
        }

        // Check MediaCapabilities for AV1 decoding support
        const config = {
          type: 'webrtc' as MediaDecodingType,
          video: {
            contentType: 'video/av1',
            width: 1920,
            height: 1080,
            framerate: 60,
            bitrate: 15000000, // 15 Mbps
          },
        };

        const result = await navigator.mediaCapabilities.decodingInfo(config);
        return result.supported;
      } catch (error) {
        console.warn('Error checking AV1 support:', error);
        return false;
      }
    },
    message: 'AV1 codec support is recommended for optimal streaming quality',
  },
];

export async function checkCapabilities(): Promise<{
  success: boolean;
  failures: string[];
  warnings: string[];
}> {
  const failures: string[] = [];
  const warnings: string[] = [];
  const requiredFailures: string[] = [];

  for (const capability of capabilities) {
    try {
      const result = await Promise.resolve(capability.check());
      if (!result) {
        if (capability.required) {
          requiredFailures.push(capability.message);
          console.error(`Required capability missing: ${capability.message}`);
        } else {
          warnings.push(capability.message);
          console.warn(`Optional capability missing: ${capability.message}`);
        }
        failures.push(capability.message);
      }
    } catch (error) {
      if (capability.required) {
        requiredFailures.push(capability.message);
        console.error(`Error checking required capability ${capability.name}:`, error);
      } else {
        warnings.push(capability.message);
        console.warn(`Error checking optional capability ${capability.name}:`, error);
      }
      failures.push(capability.message);
    }
  }

  return {
    success: requiredFailures.length === 0,
    failures,
    warnings,
  };
}
