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
    if (window.xrDevice) {
      ensureRuntimeInstalled(window.xrDevice, IWERGlobal);
      installNavigatorXRShim(window.xrDevice, IWERGlobal);
      installMakeXRCompatibleShim();
      return true;
    }

    const XRDeviceCtor = IWERGlobal.XRDevice;
    const deviceProfile = IWERGlobal.metaQuest3;
    if (!XRDeviceCtor || !deviceProfile) {
      console.warn('Bundled IWER module is missing XRDevice or metaQuest3.');
      return false;
    }

    const device: XRDevice = new XRDeviceCtor(deviceProfile);
    ensureRuntimeInstalled(device, IWERGlobal);
    installNavigatorXRShim(device, IWERGlobal);
    installMakeXRCompatibleShim();
    window.xrDevice = device;
    const supportsVr = await (navigator.xr as XRSystem | undefined)
      ?.isSessionSupported?.('immersive-vr')
      .catch(() => false);
    console.info('Bundled IWER runtime installed.', {
      navigatorXR: navigator.xr?.constructor?.name ?? '',
      requestSession: String((navigator.xr as XRSystem | undefined)?.requestSession).slice(
        0,
        80
      ),
      supportsImmersiveVr: Boolean(supportsVr),
      supportedSessionModes: readSupportedSessionModes(device, IWERGlobal),
    });
    return true;
  } catch (e) {
    console.warn('IWER runtime install failed:', e);
    return false;
  }
}

function ensureRuntimeInstalled(device: XRDevice, IWERGlobal: any): void {
  const privateDevice = readPrivateDevice(device, IWERGlobal);
  if (privateDevice?.xrSystem && navigator.xr === privateDevice.xrSystem) {
    return;
  }

  (device as any).installRuntime?.({ forceInstall: true });
}

function readPrivateDevice(device: XRDevice, IWERGlobal: any): any {
  try {
    return IWERGlobal.P_DEVICE ? (device as any)[IWERGlobal.P_DEVICE] : undefined;
  } catch (_) {
    return undefined;
  }
}

function readSupportedSessionModes(device: XRDevice, IWERGlobal: any): string[] {
  try {
    const privateDevice = readPrivateDevice(device, IWERGlobal);
    const modes = (device as any).supportedSessionModes ?? privateDevice?.supportedSessionModes;
    return Array.isArray(modes) ? modes : [];
  } catch (_) {
    return [];
  }
}

function installNavigatorXRShim(device: XRDevice, IWERGlobal: any): void {
  const xrSystem = (() => {
    try {
      const privateDevice = readPrivateDevice(device, IWERGlobal);
      return privateDevice?.xrSystem ?? (navigator.xr as XRSystem | undefined);
    } catch (_) {
      return navigator.xr as XRSystem | undefined;
    }
  })();
  if (!xrSystem) {
    return;
  }

  const defineXR = (target: object | undefined) => {
    if (!target) {
      return;
    }
    try {
      Object.defineProperty(target, 'xr', {
        value: xrSystem,
        configurable: true,
      });
    } catch (_) {}
  };

  defineXR(window.navigator);
  defineXR(Object.getPrototypeOf(window.navigator));
}

function installMakeXRCompatibleShim(): void {
  const install = (ctor: unknown) => {
    const prototype = (ctor as { prototype?: Record<string, unknown> } | undefined)?.prototype;
    if (!prototype) {
      return;
    }
    Object.defineProperty(prototype, 'makeXRCompatible', {
      value: () => Promise.resolve(),
      configurable: true,
    });
  };

  install((window as any).WebGLRenderingContext);
  install((window as any).WebGL2RenderingContext);
}

export async function loadIWERIfNeeded(forceIWER = false): Promise<IWERLoadResult> {
  if (forceIWER && window.xrDevice) {
    return { supportsImmersive: true, iwerLoaded: true };
  }

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
