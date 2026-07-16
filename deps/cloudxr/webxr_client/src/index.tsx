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

import React from 'react';
import ReactDOM from 'react-dom/client';

import { loadIWERIfNeeded } from '@helpers/LoadIWER';
import { mountBuildInfoOverlayIfRequested } from './BuildInfoOverlay';

function isEnabled(value: string | null): boolean {
  return value === '1' || value?.toLowerCase() === 'true';
}

function shouldPreloadIWERForHeadlessOob(): boolean {
  const params = new URLSearchParams(window.location.search);
  return (
    isEnabled(params.get('oobEnable')) &&
    isEnabled(params.get('autoConnect')) &&
    isEnabled(params.get('headless'))
  );
}

async function preloadIWERForHeadlessOob() {
  if (!shouldPreloadIWERForHeadlessOob()) {
    return;
  }

  const { supportsImmersive, iwerLoaded } = await loadIWERIfNeeded(true);
  if (supportsImmersive && iwerLoaded) {
    sessionStorage.setItem('iwerWasLoaded', 'true');
    sessionStorage.setItem('iwerPreloaded', 'true');
    return;
  }

  sessionStorage.removeItem('iwerPreloaded');
}

// Start the React app immediately in the 3d-ui container
async function startApp() {
  const reactContainer = document.getElementById('3d-ui');

  if (reactContainer) {
    await preloadIWERForHeadlessOob();
    const { default: App } = await import('./App');
    const root = ReactDOM.createRoot(reactContainer);
    root.render(
      <React.StrictMode>
        <App />
      </React.StrictMode>
    );
  } else {
    console.error('3d-ui container not found');
  }

  mountBuildInfoOverlayIfRequested();
}

// Initialize the app when DOM is ready
if (document.readyState === 'loading') {
  document.addEventListener('DOMContentLoaded', startApp);
} else {
  void startApp();
}
