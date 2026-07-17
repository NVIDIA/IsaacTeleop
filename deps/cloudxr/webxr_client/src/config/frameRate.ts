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

/** Logging sink used by {@link applyTargetFrameRate} to report how negotiation went. */
export interface FrameRateLogger {
  /** Reports the applied rate on the happy path. */
  info: (...args: unknown[]) => void;
  /** Reports every fallback: invalid or unsupported rates, rejections, timeouts, stale attributes. */
  warn: (...args: unknown[]) => void;
}

/** Timing overrides for {@link applyTargetFrameRate}, mainly useful in tests. */
export interface ApplyTargetFrameRateOptions {
  /** Give up waiting for updateTargetFrameRate() after this long, without failing the session. */
  updateTimeoutMs?: number;
  /** After the update resolves, wait at most this long for session.frameRate to report the new rate. */
  rateSettleGraceMs?: number;
}

const DEFAULT_UPDATE_TIMEOUT_MS = 2000;
const DEFAULT_RATE_SETTLE_GRACE_MS = 500;

/**
 * Narrows an unknown value to a number usable as a frame rate.
 *
 * @param value - Candidate value, typically session.frameRate or a configured rate.
 * @returns True when the value is a finite number greater than zero.
 */
function isFinitePositive(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

/**
 * Checks whether a supported-rates list contains the target rate.
 *
 * @param values - session.supportedFrameRates when exposed; a Float32Array, hence ArrayLike.
 * @param target - Frame rate to look for.
 * @returns True when the target rate is present in the list.
 */
function containsFrameRate(values: ArrayLike<number> | undefined, target: number): boolean {
  if (!values) return false;
  for (let index = 0; index < values.length; index += 1) {
    if (values[index] === target) return true;
  }
  return false;
}

/** How a bounded wait on updateTargetFrameRate() ended. */
type UpdateOutcome =
  | { kind: 'updated' }
  | { kind: 'timeout' }
  | { kind: 'rejected'; error: unknown };

/**
 * Awaits an updateTargetFrameRate() promise, but never longer than timeoutMs.
 *
 * The returned promise always resolves, never rejects: a hung updateTargetFrameRate()
 * must not block CloudXR session creation (an unbounded wait left the Quest stuck at
 * its loading screen), so a hang surfaces as a 'timeout' outcome and a rejection as
 * a 'rejected' outcome for the caller to fall back on. The timer is cleared once the
 * race settles so it cannot fire after the outcome is decided or leave a stray timer
 * pending.
 *
 * @param update - Promise returned by session.updateTargetFrameRate().
 * @param timeoutMs - Upper bound on how long to wait for the update.
 * @returns The outcome of the race; never a rejection.
 */
function raceUpdateAgainstTimeout(update: Promise<void>, timeoutMs: number): Promise<UpdateOutcome> {
  let timer!: ReturnType<typeof setTimeout>;
  const timeout = new Promise<UpdateOutcome>(resolve => {
    timer = setTimeout(() => resolve({ kind: 'timeout' }), timeoutMs);
  });
  const settled = update.then(
    (): UpdateOutcome => ({ kind: 'updated' }),
    (error: unknown): UpdateOutcome => ({ kind: 'rejected', error })
  );
  return Promise.race([settled, timeout]).finally(() => clearTimeout(timer));
}

/**
 * Waits until session.frameRate reports the accepted target rate, bounded by graceMs.
 *
 * The WebXR spec allows session.frameRate to keep its old value when
 * updateTargetFrameRate() resolves; the attribute change only becomes observable
 * through a later "frameratechange" event. Waiting briefly for that event avoids
 * advertising a stale rate to CloudXR.
 *
 * This promise bridges an event listener and a timer and owns the listener's
 * lifecycle: the `done` flag makes finish() idempotent, so whichever of the event,
 * the timer, or the synchronous re-check wins cannot resolve twice or leave the
 * listener attached.
 *
 * @param session - Active WebXR session.
 * @param targetFrameRate - Rate already accepted by updateTargetFrameRate().
 * @param graceMs - Upper bound on how long to wait for the event.
 * @returns Resolves once the rate is reported or the grace period elapses.
 */
function waitForReportedFrameRate(
  session: XRSession,
  targetFrameRate: number,
  graceMs: number
): Promise<void> {
  if (!session.addEventListener) {
    return Promise.resolve();
  }
  return new Promise(resolve => {
    let done = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const finish = () => {
      if (done) return;
      done = true;
      if (timer !== undefined) clearTimeout(timer);
      session.removeEventListener?.('frameratechange', onChange);
      resolve();
    };
    const onChange = () => {
      if (session.frameRate === targetFrameRate) finish();
    };
    session.addEventListener('frameratechange', onChange);
    timer = setTimeout(finish, graceMs);
    if (session.frameRate === targetFrameRate) finish();
  });
}

/**
 * Applies a headset frame rate and waits for the browser before CloudXR negotiates its stream.
 *
 * Works in two phases. Phase 1 applies the rate with a bounded wait: validate the
 * request, ask the browser, and never wait longer than updateTimeoutMs. Phase 2
 * confirms what the session reports and chooses the honest rate to advertise.
 *
 * @param session - Active WebXR session. The frame-rate members are optional per
 *   spec, so every absence path falls back instead of failing the session.
 * @param targetFrameRate - Desired rate from the client configuration.
 * @param logger - Sink for negotiation progress; defaults to console.
 * @param options - Timeout and grace overrides, mainly for tests.
 * @returns The effective rate to advertise to CloudXR.
 */
export async function applyTargetFrameRate(
  session: XRSession,
  targetFrameRate: number,
  logger: FrameRateLogger = console,
  options: ApplyTargetFrameRateOptions = {}
): Promise<number> {
  const updateTimeoutMs = options.updateTimeoutMs ?? DEFAULT_UPDATE_TIMEOUT_MS;
  const rateSettleGraceMs = options.rateSettleGraceMs ?? DEFAULT_RATE_SETTLE_GRACE_MS;

  // The honest rate to advertise whenever the target cannot be applied: whatever the
  // browser currently reports, or the requested target if nothing is reported.
  const currentFrameRate = isFinitePositive(session.frameRate) ? session.frameRate : undefined;
  const fallbackFrameRate = currentFrameRate ?? targetFrameRate;

  // Phase 1: apply the rate, with every wait bounded.

  // Reject values that cannot be a frame rate (NaN, zero, negatives).
  if (!isFinitePositive(targetFrameRate)) {
    logger.warn('Ignoring invalid target WebXR frame rate:', targetFrameRate);
    return fallbackFrameRate;
  }

  // Browsers that do not expose the optional frame-rate API keep their default rate.
  if (!session.updateTargetFrameRate || !session.supportedFrameRates) {
    logger.warn(
      'WebXR target frame-rate API is unavailable; using the current/default frame rate:',
      fallbackFrameRate
    );
    return fallbackFrameRate;
  }

  // Never request a rate the device does not list; the browser would reject it.
  if (!containsFrameRate(session.supportedFrameRates, targetFrameRate)) {
    logger.warn(
      'Requested WebXR frame rate is not supported by this device:',
      targetFrameRate
    );
    return fallbackFrameRate;
  }

  // updateTargetFrameRate() can throw synchronously as well as reject.
  let update: Promise<void>;
  try {
    update = session.updateTargetFrameRate(targetFrameRate);
  } catch (error) {
    logger.warn('Failed to apply the requested WebXR frame rate:', targetFrameRate, error);
    return fallbackFrameRate;
  }

  // Bounded wait: a hung update must not block CloudXR session creation.
  const outcome = await raceUpdateAgainstTimeout(update, updateTimeoutMs);

  if (outcome.kind === 'timeout') {
    logger.warn(
      `updateTargetFrameRate(${targetFrameRate}) did not settle within ${updateTimeoutMs} ms; ` +
        'continuing so CloudXR negotiation is not blocked. Advertising the known rate:',
      fallbackFrameRate
    );
    return fallbackFrameRate;
  }

  if (outcome.kind === 'rejected') {
    logger.warn('Failed to apply the requested WebXR frame rate:', targetFrameRate, outcome.error);
    return fallbackFrameRate;
  }

  // Phase 2: confirm the reported rate and choose what to advertise.

  // Per the WebXR spec the attribute may lag the accepted update until a
  // "frameratechange" event fires; undefined means it is not exposed at all.
  const reportsStaleRate = () =>
    session.frameRate !== undefined && session.frameRate !== targetFrameRate;

  // Give the attribute a bounded chance to settle before reading it.
  if (reportsStaleRate()) {
    await waitForReportedFrameRate(session, targetFrameRate, rateSettleGraceMs);
  }

  // A resolved updateTargetFrameRate() means the device accepted the rate change,
  // so the accepted target is the honest rate to advertise even when the attribute
  // still lags past the grace period.
  if (reportsStaleRate()) {
    logger.warn(
      `Browser still reports ${session.frameRate} Hz after accepting ${targetFrameRate} Hz; ` +
        'advertising the accepted target to CloudXR.'
    );
  } else {
    logger.info('WebXR frame rate applied before CloudXR negotiation:', targetFrameRate);
  }
  return targetFrameRate;
}
