/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

import type { ClientMode, FlowStep } from './types';

export interface HubRoute {
  step: FlowStep;
  mode?: ClientMode;
}

const HASH_TO_ROUTE: Record<string, HubRoute> = {
  configure: { step: 'configure' },
  setup: { step: 'configure' },
  desktop: { step: 'configure', mode: 'desktop' },
  join: { step: 'join' },
  headset: { step: 'join', mode: 'xr-headset' },
  immersive: { step: 'join', mode: 'xr-headset' },
  'xr-headset': { step: 'join', mode: 'xr-headset' },
  'neck-worn': { step: 'join', mode: 'neck-worn' },
  connect: { step: 'join', mode: 'desktop' },
  preflight: { step: 'preflight' },
  'pre-flight': { step: 'preflight' },
  live: { step: 'live' },
};

export function routeFromHash(hash: string): HubRoute {
  const key = hash.replace(/^#\/?/, '').split(/[?&/]/, 1)[0].toLowerCase();
  return HASH_TO_ROUTE[key] ?? { step: 'configure' };
}

export function stepFromHash(hash: string): FlowStep {
  return routeFromHash(hash).step;
}

export function hashForStep(step: FlowStep): string {
  return step === 'preflight' ? '#preflight' : `#${step}`;
}
