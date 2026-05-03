/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 *
 * Licensed under the Apache License, Version 2.0 (the "License");
 * you may not use this file except in compliance with the License.
 * You may obtain a copy of the License at
 *
 * http://www.apache.org/licenses/LICENSE-2.0
 */

// Build identity injected by webpack DefinePlugin (see webpack.common.js).
// Always logged on startup so devtools surfaces the running version even
// when the overlay is hidden.
export const BUILD_INFO = {
  teleopVersion: process.env.CLIENT_TELEOP_VERSION || 'dev',
  sdkVersion: process.env.CLIENT_SDK_VERSION || 'unknown',
  gitRef: process.env.CLIENT_GIT_REF || 'unknown',
  gitSha: process.env.CLIENT_GIT_SHA || 'unknown',
  buildTime: process.env.CLIENT_BUILD_TIME || 'unknown',
} as const;

console.info(
  `[Isaac Teleop Web Client] teleop=${BUILD_INFO.teleopVersion} sdk=${BUILD_INFO.sdkVersion} ` +
    `ref=${BUILD_INFO.gitRef}@${BUILD_INFO.gitSha} built=${BUILD_INFO.buildTime}`
);

function isOverlayRequested(): boolean {
  if (typeof window === 'undefined') return false;
  const v = new URLSearchParams(window.location.search).get('showVersion');
  return v === '1' || v?.toLowerCase() === 'true';
}

/**
 * Small fixed-corner overlay that prints the deployed build identity.
 * Appended to <body> directly so it stays visible even while the React
 * tree is mounting / unmounting and is unaffected by xr-mode CSS that
 * hides the 2D UI.
 */
export function mountBuildInfoOverlayIfRequested(): void {
  if (typeof document === 'undefined' || !isOverlayRequested()) return;
  if (document.getElementById('teleop-build-info-overlay')) return;

  const el = document.createElement('div');
  el.id = 'teleop-build-info-overlay';
  el.setAttribute('role', 'status');
  el.style.cssText = [
    'position:fixed',
    'left:8px',
    'bottom:8px',
    'z-index:99999',
    'padding:8px 10px',
    'font:12px/1.4 ui-monospace,SFMono-Regular,Menlo,Consolas,monospace',
    'color:#fff',
    'background:rgba(0,0,0,0.78)',
    'border:1px solid #76b900',
    'border-radius:4px',
    'pointer-events:auto',
    'max-width:360px',
    'word-break:break-all',
  ].join(';');
  el.textContent =
    `Teleop ${BUILD_INFO.teleopVersion} · SDK ${BUILD_INFO.sdkVersion}\n` +
    `${BUILD_INFO.gitRef}@${BUILD_INFO.gitSha}\n` +
    `built ${BUILD_INFO.buildTime}`;
  el.style.whiteSpace = 'pre';
  el.title = 'Click to dismiss';
  el.addEventListener('click', () => el.remove());
  document.body.appendChild(el);
}
