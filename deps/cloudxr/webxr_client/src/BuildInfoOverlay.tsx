/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

const BUILD_INFO = {
  teleopVersion: process.env.CLIENT_TELEOP_VERSION,
  sdkVersion: process.env.CLIENT_SDK_VERSION,
  gitRef: process.env.CLIENT_GIT_REF,
  gitSha: process.env.CLIENT_GIT_SHA,
  buildTime: process.env.CLIENT_BUILD_TIME,
};

console.info(
  `[Isaac Teleop Web Client] teleop=${BUILD_INFO.teleopVersion} sdk=${BUILD_INFO.sdkVersion} ` +
    `ref=${BUILD_INFO.gitRef}@${BUILD_INFO.gitSha} built=${BUILD_INFO.buildTime}`
);

export function mountBuildInfoOverlayIfRequested(): void {
  if (new URLSearchParams(window.location.search).get('showVersion') !== '1') return;
  const el = document.createElement('div');
  el.id = 'teleop-build-info-overlay';
  el.style.cssText =
    'position:fixed;left:8px;bottom:8px;z-index:99999;padding:8px 10px;' +
    'font:12px/1.4 ui-monospace,Menlo,Consolas,monospace;color:#fff;' +
    'background:rgba(0,0,0,0.78);border:1px solid #76b900;border-radius:4px;' +
    'pointer-events:none;white-space:pre';
  el.textContent =
    `Teleop ${BUILD_INFO.teleopVersion} · SDK ${BUILD_INFO.sdkVersion}\n` +
    `${BUILD_INFO.gitRef}@${BUILD_INFO.gitSha}\n` +
    `built ${BUILD_INFO.buildTime}`;
  document.body.appendChild(el);
}
