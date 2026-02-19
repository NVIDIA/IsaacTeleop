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

const IWER_version = '2.1.1';
const IWER_DEVUI_version = '1.1.2';

export interface IWERLoadResult {
  supportsImmersive: boolean;
  iwerLoaded: boolean;
}

export async function loadIWERIfNeeded(): Promise<IWERLoadResult> {
  let supportsImmersive = false;
  let iwerLoaded = false;

  if ('xr' in navigator) {
    try {
      const vr = await (navigator.xr as XRSystem).isSessionSupported?.('immersive-vr');
      const ar = await (navigator.xr as XRSystem).isSessionSupported?.('immersive-ar');
      supportsImmersive = Boolean(vr || ar);
    } catch (_) {}
  }

  if (!supportsImmersive) {
    console.info('Immersive mode not supported, loading IWER as fallback.');

    // Load IWER first
    const script = document.createElement('script');
    script.src = `https://unpkg.com/iwer@${IWER_version}/build/iwer.min.js`;
    script.async = true;
    script.integrity = 'sha384-ZOdYbNlfA4q9jkBGcdmjy2ZYmjxy2uzncU6it3cPOHi12/WF048bamSU0Z5N+V5u';
    script.crossOrigin = 'anonymous';

    await new Promise<void>(resolve => {
      script.onload = async () => {
        console.info('IWER loaded as fallback.');
        const IWERGlobal = (window as any).IWER || (globalThis as any).IWER;
        if (!IWERGlobal) {
          console.warn('IWER global not found after script load.');
          supportsImmersive = false;
          resolve();
          return;
        }

        // Load iwer-devui after IWER
        const devUIScript = document.createElement('script');
        devUIScript.src = `https://unpkg.com/@iwer/devui@${IWER_DEVUI_version}/build/iwer-devui.min.js`;
        devUIScript.async = true;
        devUIScript.integrity =
          'sha384-CG/gISX6PadiSzc8i2paU7CYLVsnVJaJ0tgoVnAPq/gyiTX6bddG5rwOgMDGlq74';
        devUIScript.crossOrigin = 'anonymous';

        await new Promise<void>(devUIResolve => {
          devUIScript.onload = () => {
            console.info('IWER DevUI loaded.');
            devUIResolve();
          };
          devUIScript.onerror = error => {
            console.warn('Failed to load IWER DevUI:', error);
            devUIResolve();
          };
          document.head.appendChild(devUIScript);
        });

        try {
          // Create XRDevice with Meta Quest 3 profile
          const xrDevice = new IWERGlobal.XRDevice(IWERGlobal.metaQuest3);

          // Initialize DevUI with the XR device
          const IWER_DevUI = (window as any).IWER_DevUI || (globalThis as any).IWER_DevUI;
          if (IWER_DevUI?.DevUI) {
            xrDevice.installDevUI(IWER_DevUI.DevUI);
            console.info('IWER DevUI initialized with XR device.');
          } else {
            console.warn('IWER DevUI not found after script load, continuing without DevUI.');
          }

          // Install the runtime and wait for it to be ready
          const maybePromise = xrDevice.installRuntime?.();
          if (maybePromise && typeof maybePromise.then === 'function') {
            await maybePromise;
          }
          supportsImmersive = true;
          iwerLoaded = true;
        } catch (e) {
          console.warn('IWER runtime install failed:', e);
          supportsImmersive = false;
        }
        resolve();
      };
      script.onerror = () => {
        console.warn('Failed to load IWER.');
        supportsImmersive = false;
        resolve();
      };
      document.head.appendChild(script);
    });
  }

  return { supportsImmersive, iwerLoaded };
}
