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
 * Single source of truth for every URL query parameter the web client accepts.
 *
 * Two kinds of param live here:
 *  - form-backed (has `elementId`): seeded into a control in index.html, then read
 *    back through the form into the CloudXR config.
 *  - direct (no `elementId`): consumed straight from the URL by app logic (transport
 *    and session bootstrap, e.g. TURN/ICE and the OOB hub). Never seeded or stored.
 *
 * See resolve.ts for how each kind is read.
 */
export interface UrlParam {
  /** Canonical identifier for the parameter. */
  key: string;
  /** URL query parameter name. Defaults to `key` when omitted. */
  url?: string;
  /** id of the bound form control in index.html. Present only for form-backed params. */
  elementId?: string;
  /** How a form-backed value is applied to the control. Defaults to 'value'. */
  kind?: 'value' | 'checked';
  /** Optional check for the raw URL string; invalid values are ignored. */
  isValid?: (raw: string) => boolean;
}

const oneOf =
  (...allowed: string[]) =>
  (raw: string): boolean =>
    allowed.includes(raw);
const isBool = oneOf('true', 'false');
const isNumber = (raw: string): boolean => raw.trim() !== '' && Number.isFinite(Number(raw));

export const URL_PARAMS: UrlParam[] = [
  // --- Form-backed settings (seeded into a control, then read through the form) ---
  { key: 'serverIP', elementId: 'serverIpInput' },
  { key: 'port', elementId: 'portInput', isValid: isNumber },
  { key: 'serverType', elementId: 'serverType', isValid: oneOf('manual', 'nvcf') },
  { key: 'codec', elementId: 'codec', isValid: oneOf('h264', 'h265', 'av1') },
  { key: 'immersiveMode', elementId: 'immersive', isValid: oneOf('ar', 'vr') },
  // deviceProfile is intentionally omitted: it is a preset that bulk-fills the fields below via a
  // change handler, which programmatic seeding does not trigger. Set the individual fields instead.
  { key: 'deviceFrameRate', elementId: 'deviceFrameRate', isValid: isNumber },
  { key: 'maxStreamingBitrateMbps', elementId: 'maxStreamingBitrateMbps', isValid: isNumber },
  { key: 'perEyeWidth', elementId: 'perEyeWidth', isValid: isNumber },
  { key: 'perEyeHeight', elementId: 'perEyeHeight', isValid: isNumber },
  { key: 'reprojectionGridCols', elementId: 'reprojectionGridCols', isValid: isNumber },
  { key: 'reprojectionGridRows', elementId: 'reprojectionGridRows', isValid: isNumber },
  { key: 'enablePoseSmoothing', elementId: 'enablePoseSmoothing', isValid: isBool },
  { key: 'posePredictionFactor', elementId: 'posePredictionFactor', isValid: isNumber },
  { key: 'enableTexSubImage2D', elementId: 'enableTexSubImage2D', isValid: isBool },
  { key: 'useQuestColorWorkaround', elementId: 'useQuestColorWorkaround', isValid: isBool },
  { key: 'referenceSpace', elementId: 'referenceSpace', isValid: oneOf('auto', 'local-floor', 'local', 'viewer', 'unbounded') },
  { key: 'xrOffsetX', elementId: 'xrOffsetX', isValid: isNumber },
  { key: 'xrOffsetY', elementId: 'xrOffsetY', isValid: isNumber },
  { key: 'xrOffsetZ', elementId: 'xrOffsetZ', isValid: isNumber },
  { key: 'controlPanelPosition', elementId: 'controlPanelPosition', isValid: oneOf('left', 'center', 'right') },
  { key: 'controllerModelVisibility', elementId: 'controllerModelVisibility', isValid: oneOf('show', 'hide') },
  { key: 'panelHiddenAtStart', elementId: 'panelHiddenAtStart', isValid: isBool },
  { key: 'headless', elementId: 'cloudxrHeadless', kind: 'checked', isValid: isBool },
  { key: 'autoRefreshMode', elementId: 'cloudxrAutoRefreshMode', isValid: oneOf('never', 'clean', 'any') },
  { key: 'proxyUrl', elementId: 'proxyUrl' },
  { key: 'mediaAddress', elementId: 'mediaAddress' },
  { key: 'mediaPort', elementId: 'mediaPort', isValid: isNumber },

  // --- Direct params: read straight from the URL by app logic (no control, never stored) ---
  // TURN/ICE for NAT traversal and OOB hub, typically set in USB-local mode by oob_teleop_env.py.
  // No `isValid` here: the consumers apply their own interpretation (exact matching, regex, etc.).
  { key: 'turnServer' },
  { key: 'turnUsername' },
  { key: 'turnCredential' },
  { key: 'iceRelayOnly' },
  { key: 'oobEnable' },
  { key: 'controlToken' },
];
