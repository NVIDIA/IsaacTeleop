// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

import { defineConfig, devices } from '@playwright/test';

const baseURL = process.env.WEB_URL ?? 'http://cloudxr-runtime:8080';

export default defineConfig({
  testDir: '.',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  // Catch stray test.only commits in CI runs.
  forbidOnly: !!process.env.CI,
  retries: process.env.CI ? 1 : 0,
  // Artifact policy:
  //   - results.json: structured pass/fail summary on every run.
  //   - video.webm:   recorded on every run (visual confirmation of
  //                   streaming, not just a failure aid).
  //   - trace.zip:    only when a test fails, since it's the largest blob.
  //   - screenshot:   only-on-failure (the spec also takes an explicit
  //                   streaming.png unconditionally for green-run evidence).
  reporter: [
    ['list'],
    ['json', { outputFile: 'test-results/results.json' }],
  ],
  use: {
    baseURL,
    trace: 'retain-on-failure',
    video: 'on',
    screenshot: 'only-on-failure',
    launchOptions: {
      args: [
        '--no-sandbox',
        '--disable-setuid-sandbox',
        '--ignore-gpu-blocklist',
        '--enable-webgl',
        // Disable WebXR so Chromium does not advertise navigator.xr from a
        // host-registered OpenXR runtime; helpers/LoadIWER.ts then falls
        // back to IWER's mock XRDevice, which is what the spec relies on.
        '--disable-features=WebXR',
        // Force a CPU-rendered GL stack so @react-three/fiber's
        // WebGLRenderer can always create a context, even without GPU
        // access in the Playwright container or on a headless macOS host.
        '--use-angle=swiftshader',
        '--use-gl=angle',
        '--enable-gpu-rasterization',
        '--in-process-gpu',
      ],
    },
  },
  projects: [
    {
      name: 'chromium',
      use: { ...devices['Desktop Chrome'] },
    },
  ],
});
