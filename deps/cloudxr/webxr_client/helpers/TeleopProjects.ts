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

import type { ControlPanelPosition, TeleopMode } from './react/utils';

/** Per-project settings that override mode-level defaults. */
export interface TeleopProjectSettings {
  panelHiddenAtStart?: boolean;
  controlPanelPosition?: ControlPanelPosition;
}

/**
 * A node in the project registry tree.
 * Nodes with `settings` are selectable destinations.
 * Nodes with only `children` are organizational groups (rendered as disabled headers in the dropdown).
 * A node can have both (selectable AND has children).
 */
export interface TeleopProjectNode {
  label: string;
  settings?: TeleopProjectSettings;
  children?: Record<string, TeleopProjectNode>;
}

export type TeleopProjectRegistry = Record<TeleopMode, TeleopProjectNode>;

export const TELEOP_PROJECTS: TeleopProjectRegistry = {
  sim: {
    label: 'IsaacSim',
    settings: { panelHiddenAtStart: false },
  },
  real: {
    label: 'Real Robot',
    settings: { panelHiddenAtStart: true },
    children: {
      gear: {
        label: 'GEAR',
        settings: {},
        children: {
          dexmate: { label: 'DexMate', settings: {} },
          g1: { label: 'G1', settings: {} },
          lerobot: { label: 'LeRobot', settings: { panelHiddenAtStart: false, controlPanelPosition: 'left' } },
        },
      },
    },
  },
};

/**
 * Walks the registry tree to find the node matching `mode` + optional `subproject` path.
 * @param subproject - Slash-separated path segments after the mode (e.g. "gear/dexmate").
 */
export function resolveProjectNode(
  mode: TeleopMode,
  subproject?: string,
): TeleopProjectNode | null {
  const root = TELEOP_PROJECTS[mode];
  if (!root) return null;
  if (!subproject) return root;

  const segments = subproject.split('/').filter(Boolean);
  let current: TeleopProjectNode = root;
  for (const seg of segments) {
    if (!current.children?.[seg]) return null;
    current = current.children[seg];
  }
  return current;
}

/** Walks the ancestor chain from root to the target node, merging settings at each level. */
export function getProjectSettings(
  mode: TeleopMode,
  subproject?: string,
): TeleopProjectSettings {
  const root = TELEOP_PROJECTS[mode];
  if (!root) return {};
  let merged: TeleopProjectSettings = { ...root.settings };
  if (!subproject) return merged;

  const segments = subproject.split('/').filter(Boolean);
  let current: TeleopProjectNode = root;
  for (const seg of segments) {
    if (!current.children?.[seg]) break;
    current = current.children[seg];
    if (current.settings) {
      merged = { ...merged, ...current.settings };
    }
  }
  return merged;
}

/** Returns the resolved node's label, falling back to the mode root's label. */
export function getProjectLabel(
  mode: TeleopMode,
  subproject?: string,
): string {
  const node = resolveProjectNode(mode, subproject);
  if (node) return node.label;
  const root = TELEOP_PROJECTS[mode];
  return root?.label ?? mode;
}

export interface DropdownEntry {
  hash: string;
  label: string;
  depth: number;
  disabled: boolean;
}

/** Recursively flattens the registry tree into a list suitable for a `<select>` element. */
export function flattenRegistryForDropdown(): DropdownEntry[] {
  const entries: DropdownEntry[] = [];

  function walk(node: TeleopProjectNode, hashPrefix: string, depth: number): void {
    const selectable = node.settings !== undefined;
    entries.push({
      hash: `#/${hashPrefix}`,
      label: node.label,
      depth,
      disabled: !selectable,
    });
    if (node.children) {
      for (const [key, child] of Object.entries(node.children)) {
        walk(child, `${hashPrefix}/${key}`, depth + 1);
      }
    }
  }

  for (const mode of ['sim', 'real'] as TeleopMode[]) {
    walk(TELEOP_PROJECTS[mode], mode, 0);
  }
  return entries;
}
