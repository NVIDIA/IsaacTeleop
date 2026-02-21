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
 * Shared utilities for React examples (e.g. control panel position).
 */

export type ControlPanelPosition = 'left' | 'center' | 'right';

/** React UI options (e.g. in-XR control panel position). */
export interface ReactUIConfig {
  controlPanelPosition?: ControlPanelPosition;
}

const CONTROL_PANEL_POSITIONS: readonly ControlPanelPosition[] = ['left', 'center', 'right'];

/**
 * Parses a string into a valid control panel position.
 * @param unvalidatedValue - String to validate (e.g. from URL, config, or form). May be invalid or empty.
 * @param fallback - Value to return when unvalidatedValue is not valid.
 */
export function parseControlPanelPosition(
  unvalidatedValue: string,
  fallback: ControlPanelPosition
): ControlPanelPosition {
  if (CONTROL_PANEL_POSITIONS.includes(unvalidatedValue as ControlPanelPosition)) {
    return unvalidatedValue as ControlPanelPosition;
  }
  return fallback;
}

export interface ControlPanelLayoutOptions {
  /** Distance from viewer to panel (meters). */
  distance: number;
  /** Height of panel (meters). */
  height: number;
  /** Angle in degrees for left/right positions from center. */
  angleDegrees: number;
}

/**
 * Returns [x, y, z] for the in-XR control panel. Center is in front; left/right at the given angle.
 */
export function getControlPanelPositionVector(
  pos: ControlPanelPosition,
  layout: ControlPanelLayoutOptions
): [number, number, number] {
  if (pos === 'center') {
    return [0, layout.height, -layout.distance];
  }
  const rad = (layout.angleDegrees * Math.PI) / 180;
  const x = layout.distance * Math.sin(rad);
  const z = -layout.distance * Math.cos(rad);
  return [pos === 'left' ? -x : x, layout.height, z];
}
