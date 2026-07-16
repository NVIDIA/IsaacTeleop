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

import type { XRDevice } from 'iwer';

declare global {
  interface Window {
    xrDevice?: XRDevice | null;
  }
}

export interface IWERLoadResult {
  supportsImmersive: boolean;
  iwerLoaded: boolean;
}

async function installBundledIWER(): Promise<boolean> {
  try {
    const IWERModule = await import('iwer');
    const IWERGlobal = (IWERModule as any).default ?? IWERModule;
    const XRDeviceCtor = IWERGlobal.XRDevice;
    const deviceProfile = IWERGlobal.metaQuest3;
    if (!XRDeviceCtor || !deviceProfile) {
      console.warn('Bundled IWER module is missing XRDevice or metaQuest3.');
      return false;
    }

    const device: XRDevice = new XRDeviceCtor(deviceProfile);
    await device.installRuntime();
    window.xrDevice = device;
    return true;
  } catch (e) {
    console.warn('IWER runtime install failed:', e);
    return false;
  }
}

export async function loadIWERIfNeeded(forceIWER = false): Promise<IWERLoadResult> {
  let supportsImmersive = false;
  let iwerLoaded = false;

  if (!forceIWER && 'xr' in navigator) {
    try {
      const vr = await (navigator.xr as XRSystem).isSessionSupported?.('immersive-vr');
      const ar = await (navigator.xr as XRSystem).isSessionSupported?.('immersive-ar');
      supportsImmersive = Boolean(vr || ar);
    } catch (_) {}
  }

  if (forceIWER || !supportsImmersive) {
    console.info(
      forceIWER
        ? 'Installing bundled IWER for automated headless validation.'
        : 'Immersive mode not supported, installing bundled IWER fallback.'
    );
    iwerLoaded = await installBundledIWER();
    supportsImmersive = iwerLoaded;
  }

  return { supportsImmersive, iwerLoaded };
}
