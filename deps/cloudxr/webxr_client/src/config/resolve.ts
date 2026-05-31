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

import { URL_PARAMS, type UrlParam } from './params';

/**
 * Collects the form-backed URL params present in `params`, keyed by UrlParam.key.
 * A param is included only when it has an `elementId`, its query param is present,
 * and it passes its (optional) validation. Pure — no DOM access.
 * `urlParams` is injectable for testing; it defaults to the real registry.
 */
export function seedsFromParams(
  params: URLSearchParams,
  urlParams: UrlParam[] = URL_PARAMS
): Map<string, string> {
  const seeds = new Map<string, string>();
  for (const param of urlParams) {
    if (!param.elementId) continue;
    const raw = params.get(param.url ?? param.key);
    if (raw === null) continue;
    if (param.isValid && !param.isValid(raw)) continue;
    seeds.set(param.key, raw);
  }
  return seeds;
}

/**
 * Reads a single declared URL param's value, applying its (optional) validation.
 * Returns null when the key is unknown, absent, or fails validation. Used by the
 * direct (non-form) consumers so every accepted param is declared in one place.
 * `urlParams` is injectable for testing; it defaults to the real registry.
 */
export function readUrlParam(
  params: URLSearchParams,
  key: string,
  urlParams: UrlParam[] = URL_PARAMS
): string | null {
  const param = urlParams.find(p => p.key === key);
  if (!param) return null;
  const raw = params.get(param.url ?? param.key);
  if (raw === null) return null;
  if (param.isValid && !param.isValid(raw)) return null;
  return raw;
}
