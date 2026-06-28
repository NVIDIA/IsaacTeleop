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

import { expect, test, type Page } from '@playwright/test';
import path from 'node:path';

function packageFile(packageName: string, relativePath: string): string {
  return path.join(path.dirname(require.resolve(`${packageName}/package.json`)), relativePath);
}

async function routeIwerFromNodeModules(page: Page): Promise<void> {
  const iwerScript = packageFile('iwer', 'build/iwer.min.js');
  const iwerDevUiScript = packageFile('@iwer/devui', 'build/iwer-devui.min.js');

  await page.route(/https:\/\/unpkg\.com\/iwer@[^/]+\/build\/iwer\.min\.js/, async route => {
    await route.fulfill({ path: iwerScript, contentType: 'application/javascript' });
  });
  await page.route(
    /https:\/\/unpkg\.com\/@iwer\/devui@[^/]+\/build\/iwer-devui\.min\.js/,
    async route => {
      await route.fulfill({ path: iwerDevUiScript, contentType: 'application/javascript' });
    }
  );
}

test('desktop browser path loads IWER and enables Connect', async ({ page }) => {
  await routeIwerFromNodeModules(page);

  await page.goto(
    '/?serverIP=127.0.0.1&port=49100&headless=true&autoRefreshMode=never&immersiveMode=vr',
    { waitUntil: 'domcontentloaded' }
  );

  await expect(page.locator('#serverIpInput')).toHaveValue('127.0.0.1');
  await expect(page.locator('#portInput')).toHaveValue('49100');

  await expect
    .poll(() => page.evaluate(() => Boolean((window as any).xrDevice)))
    .toBe(true);
  // Capability warnings can replace the status banner; assert the runtime state directly.
  await expect
    .poll(() => page.evaluate(() => sessionStorage.getItem('iwerWasLoaded')))
    .toBe('true');

  const supportsImmersiveVr = await page.evaluate(async () => {
    return Boolean(await navigator.xr?.isSessionSupported?.('immersive-vr'));
  });
  expect(supportsImmersiveVr).toBe(true);

  const connectButton = page.locator('#startButton');
  await expect(connectButton).toHaveText('CONNECT');
  await expect(connectButton).toBeEnabled();
});
