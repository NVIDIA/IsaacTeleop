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

import type { TeleopProjectSettings } from '../TeleopProjects';

export type ControlPanelPosition = 'left' | 'center' | 'right';

export type TeleopMode = 'sim' | 'real';

export interface TeleopModeInfo {
  mode: TeleopMode;
  subproject?: string;
}

/**
 * Extracts teleop mode and optional subproject from a URL hash fragment.
 * Follows the `#/path` convention (e.g. `#/real/gear/dexmate`).
 * @returns mode + optional subproject, or `null` if the hash doesn't start with a known mode.
 */
export function parseTeleopModeFromHash(hash: string): TeleopModeInfo | null {
  const cleaned = hash.replace(/^#\/?/, '');
  if (!cleaned) return null;
  const slashIndex = cleaned.indexOf('/');
  const modeStr = (slashIndex === -1 ? cleaned : cleaned.substring(0, slashIndex)).toLowerCase();
  if (modeStr !== 'sim' && modeStr !== 'real') return null;
  const subproject = slashIndex === -1 ? undefined : cleaned.substring(slashIndex + 1) || undefined;
  return { mode: modeStr, subproject };
}

/** Builds the localStorage key suffix from mode + optional subproject. */
function projectPath(mode: TeleopMode, subproject?: string): string {
  return subproject ? `${mode}/${subproject}` : mode;
}

/**
 * Resolves panelHiddenAtStart for the current project.
 * Priority: per-project localStorage > project registry setting > false.
 */
export function loadPanelHiddenForMode(
  mode: TeleopMode,
  subproject?: string,
  projectSettings?: TeleopProjectSettings,
): boolean {
  try {
    const stored = localStorage.getItem(`cxr.isaac.panelHiddenAtStart.${projectPath(mode, subproject)}`);
    if (stored === 'true') return true;
    if (stored === 'false') return false;
  } catch {
    /* localStorage unavailable */
  }
  return projectSettings?.panelHiddenAtStart ?? false;
}

/** Persists panelHiddenAtStart to localStorage keyed by project path. */
export function savePanelHiddenForMode(mode: TeleopMode, subproject: string | undefined, value: boolean): void {
  try {
    localStorage.setItem(`cxr.isaac.panelHiddenAtStart.${projectPath(mode, subproject)}`, String(value));
  } catch {
    /* localStorage unavailable */
  }
}

/**
 * Resolves controlPanelPosition for the current project.
 * Priority: per-project localStorage > project registry setting > 'center'.
 */
export function loadControlPanelPositionForProject(
  mode: TeleopMode,
  subproject?: string,
  projectSettings?: TeleopProjectSettings,
): ControlPanelPosition {
  try {
    const stored = localStorage.getItem(`cxr.isaac.controlPanelPosition.${projectPath(mode, subproject)}`);
    if (stored) return parseControlPanelPosition(stored, 'center');
  } catch {
    /* localStorage unavailable */
  }
  return projectSettings?.controlPanelPosition ?? 'center';
}

/** Persists controlPanelPosition to localStorage keyed by project path. */
export function saveControlPanelPositionForProject(mode: TeleopMode, subproject: string | undefined, value: ControlPanelPosition): void {
  try {
    localStorage.setItem(`cxr.isaac.controlPanelPosition.${projectPath(mode, subproject)}`, value);
  } catch {
    /* localStorage unavailable */
  }
}

/** React UI options (e.g. in-XR control panel position). */
export interface ReactUIConfig {
  controlPanelPosition?: ControlPanelPosition;
  /** When true, the control panel is hidden at immersive XR enter (small \u201cshow control panel\u201d control only). */
  panelHiddenAtStart?: boolean;
  /** Teleop mode resolved from URL hash or localStorage fallback. */
  teleopMode?: TeleopMode;
  /** Optional subproject path from the URL hash (e.g. "gear/dexmate" from #/real/gear/dexmate). */
  subproject?: string;
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
