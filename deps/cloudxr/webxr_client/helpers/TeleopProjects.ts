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

/** Per-project settings that override ancestor defaults. */
export interface TeleopProjectSettings {
  panelHiddenAtStart?: boolean;
}

/**
 * A node in the project registry tree. Nodes with `settings` contribute defaults at
 * their depth; ancestor settings are merged in priority order (deepest wins).
 */
export interface TeleopProjectNode {
  label: string;
  settings?: TeleopProjectSettings;
  children?: Record<string, TeleopProjectNode>;
}

export type TeleopProjectRegistry = Record<string, TeleopProjectNode>;

/** Default teleop path when nothing is resolvable from URL hash or localStorage. */
export const DEFAULT_TELEOP_PATH = 'sim';

/**
 * Registry of teleop projects, keyed by URL-hash path (e.g. `#/real/gear/dexmate`).
 *
 * Keys must be lowercase; URL segments are lowercased before lookup so the
 * hash is effectively case-insensitive.
 *
 * Every node in the tree (top-level keys and their descendants) is selectable,
 * so a new hardware variant can use a more general path (e.g. `#/real/gear`)
 * pending adding the specific one to this file. A descendant node's defaults
 * override its ancestors' defaults at every depth (e.g. `real/gear`'s defaults
 * override `real`'s). Per-node user overrides (localStorage) are a separate
 * layer and take priority over any registry defaults.
 */
export const TELEOP_PROJECTS: TeleopProjectRegistry = {
  sim: {
    label: 'Simulation',
    settings: { panelHiddenAtStart: false },
    children: {
      isaacsim: { label: 'IsaacSim', settings: {} },
    },
  },
  real: {
    label: 'Real Robot',
    settings: { panelHiddenAtStart: true },
    children: {
      ros: { label: 'ROS', settings: {} },
      isaacros: { label: 'IsaacROS', settings: {} },
      gear: {
        label: 'GEAR',
        settings: {},
        children: {
          dexmate: { label: 'Dexmate', settings: {} },
          g1_sonic: { label: 'G1 Sonic', settings: {} },
          g1_homie: { label: 'G1 Homie', settings: {} },
        },
      },
    },
  },
};

function pathSegments(teleopPath: string | undefined): string[] {
  if (!teleopPath) return [];
  return teleopPath.split('/').filter(Boolean);
}

/** Merges node defaults from root to target along the path; deepest non-undefined value wins. */
export function getProjectSettings(teleopPath: string | undefined): TeleopProjectSettings {
  const segments = pathSegments(teleopPath);
  if (segments.length === 0) return {};
  const root = TELEOP_PROJECTS[segments[0]];
  if (!root) return {};
  let merged: TeleopProjectSettings = { ...root.settings };
  let current: TeleopProjectNode = root;
  for (let i = 1; i < segments.length; i++) {
    const child = current.children?.[segments[i]];
    if (!child) break;
    current = child;
    if (current.settings) {
      merged = { ...merged, ...current.settings };
    }
  }
  return merged;
}

/**
 * Labels for each node along the path, from root to the deepest valid node.
 * Unknown segments terminate the walk, so `real/fake` yields just `['Real Robot']`,
 * and an unknown root yields `[]`.
 */
export function getProjectBreadcrumb(teleopPath: string | undefined): string[] {
  const segments = pathSegments(teleopPath);
  if (segments.length === 0) return [];
  const root = TELEOP_PROJECTS[segments[0]];
  if (!root) return [];
  const labels = [root.label];
  let current: TeleopProjectNode = root;
  for (let i = 1; i < segments.length; i++) {
    const child = current.children?.[segments[i]];
    if (!child) break;
    labels.push(child.label);
    current = child;
  }
  return labels;
}

/**
 * Extracts a teleop path from a URL hash fragment (e.g. `#/real/gear/dexmate`).
 * Segments are lowercased before lookup and the walk stops at the deepest valid
 * registry node, so `#/real/fake/path` canonicalizes to `real`.
 * @returns a canonicalized slash-separated path, or `null` if no registry match.
 */
export function parseTeleopPathFromHash(hash: string): string | null {
  const cleaned = hash.replace(/^#\/?/, '');
  if (!cleaned) return null;
  const segments = cleaned.split('/').filter(Boolean).map(s => s.toLowerCase());
  if (segments.length === 0) return null;
  const root = TELEOP_PROJECTS[segments[0]];
  if (!root) return null;
  const canonical: string[] = [segments[0]];
  let current: TeleopProjectNode = root;
  for (let i = 1; i < segments.length; i++) {
    const child = current.children?.[segments[i]];
    if (!child) break;
    canonical.push(segments[i]);
    current = child;
  }
  return canonical.join('/');
}

export interface DropdownEntry {
  hash: string;
  label: string;
  depth: number;
}

/**
 * Pre-flattened registry tree, suitable for a `<select>` element.
 * Computed once at module load since the registry is static.
 */
export const DROPDOWN_ENTRIES: readonly DropdownEntry[] = (() => {
  const entries: DropdownEntry[] = [];
  function walk(node: TeleopProjectNode, hashPrefix: string, depth: number): void {
    entries.push({ hash: `#/${hashPrefix}`, label: node.label, depth });
    if (node.children) {
      for (const [key, child] of Object.entries(node.children)) {
        walk(child, `${hashPrefix}/${key}`, depth + 1);
      }
    }
  }
  for (const key of Object.keys(TELEOP_PROJECTS)) {
    walk(TELEOP_PROJECTS[key], key, 0);
  }
  return entries;
})();
