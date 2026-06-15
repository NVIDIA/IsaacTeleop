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

// Minimum versions for CloudXR.js compatibility.
// Requirements: https://docs.nvidia.com/cloudxr-sdk/latest/requirement/cloudxrjs_req.html
// Quest OS version is not exposed in the UA; OculusBrowser 40 approximates the OS v79 era
// (browser 41.2, Nov 2025, was the first to declare OS v81 as its minimum).
const MIN_OCULUS_BROWSER_MAJOR = 40;
const MIN_PICO_CHROME_MAJOR = 125;

// Returns a warning message if the current browser is below the documented minimum
// version, or null if the version is acceptable or cannot be determined.
// Pass emulated=true when running under an XR emulator (e.g. IWER) to skip the check.
export function checkBrowserVersion(emulated = false): string | null {
  if (emulated) {
    return null;
  }

  const ua = navigator.userAgent;

  // Detect Pico first — Pico UAs also include "OculusBrowser/7.0" as a compat token
  // which would otherwise match the Quest check below.
  if (/PicoBrowser\//.test(ua)) {
    const chromeMatch = ua.match(/Chrome\/(\d+)\./);
    if (chromeMatch) {
      const major = parseInt(chromeMatch[1], 10);
      if (major < MIN_PICO_CHROME_MAJOR) {
        return (
          `Pico Browser (Chrome ${major}) is outdated. ` +
          `CloudXR requires Chrome ${MIN_PICO_CHROME_MAJOR} or later. ` +
          `Please update your headset firmware.`
        );
      }
    }
    return null;
  }

  const questMatch = ua.match(/OculusBrowser\/(\d+)\./);
  if (questMatch) {
    const major = parseInt(questMatch[1], 10);
    if (major < MIN_OCULUS_BROWSER_MAJOR) {
      return (
        `Meta Quest Browser version ${major} detected. ` +
        `CloudXR requires Meta Quest OS v79 or later ` +
        `(approximately OculusBrowser ${MIN_OCULUS_BROWSER_MAJOR}+). ` +
        `Please update your headset firmware.`
      );
    }
  }

  return null;
}

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
    message: 'AV1 codec is not supported on this device. H.264 or HEVC can be selected as an alternative.',
  },
  {
    name: 'HEVC Codec Support',
    required: false,
    check: async () => {
      try {
        if (!navigator.mediaCapabilities) {
          return false;
        }

        const config = {
          type: 'webrtc' as MediaDecodingType,
          video: {
            contentType: 'video/h265',
            width: 1920,
            height: 1080,
            framerate: 60,
            bitrate: 15000000,
          },
        };

        const result = await navigator.mediaCapabilities.decodingInfo(config);
        return result.supported;
      } catch (error) {
        console.warn('Error checking HEVC support:', error);
        return false;
      }
    },
    message: 'HEVC (H.265) codec is not supported on this device. H.264 or AV1 can be selected as an alternative.',
  },
];

export async function checkCapabilities(emulated = false): Promise<{
  success: boolean;
  failures: string[];
  warnings: string[];
}> {
  const failures: string[] = [];
  const warnings: string[] = [];
  const requiredFailures: string[] = [];

  // Check browser version first so the warning appears at the top of the list.
  const versionWarning = checkBrowserVersion(emulated);
  if (versionWarning) {
    warnings.push(versionWarning);
    console.warn('Browser version warning:', versionWarning);
  }

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
