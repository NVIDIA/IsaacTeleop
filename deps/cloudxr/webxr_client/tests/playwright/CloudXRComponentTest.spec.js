/*
 * SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
 * SPDX-License-Identifier: Apache-2.0
 */

// @ts-check
const { test, expect } = require('@playwright/test');

/**
 * Drives tests/mock/CloudXRComponentTest.tsx's real CloudXRComponent + MockCloudXR scripted
 * 4-step sequence in a real browser, and asserts on its console output (every line the page logs
 * is prefixed "[CloudXRComponentTest] " via appendLog() - see that file) rather than the DOM log
 * panel, so this test exercises exactly what a real integrator's console would show.
 */

const LOG_PREFIX = '[CloudXRComponentTest] ';
/** The sequence's real pacing is roughly 1s+1.5s+2.5s+3.7s of sleeps plus IWER/enterVR overhead. */
const SEQUENCE_TIMEOUT_MS = 40000;

/** Collects every "[CloudXRComponentTest] "-prefixed console line, with the prefix stripped. */
function collectLogLines(page) {
  const lines = [];
  page.on('console', msg => {
    const text = msg.text();
    if (text.startsWith(LOG_PREFIX)) {
      lines.push(text.slice(LOG_PREFIX.length));
    }
  });
  return lines;
}

/** Lines strictly between two markers (exclusive), in collection order. */
function between(lines, startMarker, endMarker) {
  const start = lines.indexOf(startMarker);
  const end = endMarker ? lines.indexOf(endMarker, start + 1) : lines.length;
  if (start === -1) return [];
  return lines.slice(start + 1, end === -1 ? lines.length : end);
}

test('CloudXRComponentTest scripted sequence: every callback fires as expected', async ({
  page,
}) => {
  test.setTimeout(SEQUENCE_TIMEOUT_MS + 20000);

  const lines = collectLogLines(page);
  await page.goto('/CloudXRComponentTest.html');
  await page.click('#startButton');

  await expect
    .poll(() => lines.includes('=== Test sequence complete ==='), {
      timeout: SEQUENCE_TIMEOUT_MS,
      message: () => `sequence did not complete; captured so far:\n${lines.join('\n')}`,
    })
    .toBe(true);

  // --- Step 1: no errors ---
  const step1Body = between(
    lines,
    '=== Step 1: start, then close cleanly - expect no errors ===',
    '=== Step 2: fail while still connecting (non-retryable) ==='
  );
  expect(step1Body).toContain('[step1] PASS: no errors');
  expect(step1Body.some(l => l.startsWith('[error]'))).toBe(false);

  // --- Step 2: unrecoverable-shaped failure while still connecting ---
  const step2Body = between(
    lines,
    '=== Step 2: fail while still connecting (non-retryable) ===',
    '=== Step 3: fail once connected (retryable) ==='
  );
  const step2Errors = step2Body.filter(l => l.startsWith('[error]'));
  expect(step2Errors).toHaveLength(1);
  expect(step2Errors[0]).toContain('Mock non-retryable failure (server-disconnect range)');

  // --- Step 3: recoverable-shaped failure once connected ---
  const step3Body = between(
    lines,
    '=== Step 3: fail once connected (retryable) ===',
    '=== Step 4: stream test (remounts with streamTest enabled) ==='
  );
  const step3Errors = step3Body.filter(l => l.startsWith('[error]'));
  expect(step3Errors).toHaveLength(1);
  expect(step3Errors[0]).toContain('Mock retryable failure (network interrupted)');

  // --- Step 4: stream test runs to completion ---
  const step4Body = between(
    lines,
    '=== Step 4: stream test (remounts with streamTest enabled) ===',
    '=== Test sequence complete ==='
  );
  const startedIdx = step4Body.indexOf('[event] onStreamTestStarted');
  const stoppedIdx = step4Body.indexOf('[event] onStreamTestStopped passed=true');
  expect(startedIdx).toBeGreaterThanOrEqual(0);
  expect(stoppedIdx).toBeGreaterThan(startedIdx);

  // --- Full CloudXRComponentProps callback surface fired at least once across the whole run ---
  expect(lines).toContain('[event] onSessionReady session');
  expect(lines).toContain('[event] onSessionReady null');
  expect(lines.some(l => l.startsWith('[event] onServerAddress '))).toBe(true);
  expect(lines.some(l => l.startsWith('[event] onLog '))).toBe(true);
  expect(lines).toContain('[event] onRenderPerformanceMetrics (first occurrence)');
  expect(lines).toContain('[event] onStreamingPerformanceMetrics (first occurrence)');
  expect(lines).toContain('[event] onNetworkPerformanceMetrics (first occurrence)');
  expect(lines).toContain('[prop] trackingFrameAdapter called');
  expect(lines.some(l => l.startsWith('[status] connected='))).toBe(true);

  // --- No stray errors outside steps 2/3 ---
  const totalErrors = lines.filter(l => l.startsWith('[error]'));
  expect(totalErrors).toHaveLength(2);
});
