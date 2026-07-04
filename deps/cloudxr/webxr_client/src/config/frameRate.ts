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

/** The optional WebXR frame-rate members used by supported headsets. */
export interface FrameRateSession {
  frameRate?: number;
  supportedFrameRates?: ArrayLike<number>;
  updateTargetFrameRate?: (rate: number) => Promise<void>;
  addEventListener?: (type: string, listener: () => void) => void;
  removeEventListener?: (type: string, listener: () => void) => void;
}

export interface FrameRateLogger {
  info: (...args: unknown[]) => void;
  warn: (...args: unknown[]) => void;
}

export interface ApplyTargetFrameRateOptions {
  /** Give up waiting for updateTargetFrameRate() after this long, without failing the session. */
  updateTimeoutMs?: number;
  /** After the update resolves, wait at most this long for session.frameRate to report the new rate. */
  rateSettleGraceMs?: number;
}

const DEFAULT_UPDATE_TIMEOUT_MS = 2000;
const DEFAULT_RATE_SETTLE_GRACE_MS = 500;

function isFinitePositive(value: unknown): value is number {
  return typeof value === 'number' && Number.isFinite(value) && value > 0;
}

function containsFrameRate(values: ArrayLike<number> | undefined, target: number): boolean {
  if (!values) return false;
  for (let index = 0; index < values.length; index += 1) {
    if (values[index] === target) return true;
  }
  return false;
}

type UpdateOutcome =
  | { kind: 'updated' }
  | { kind: 'timeout' }
  | { kind: 'rejected'; error: unknown };

function raceUpdateAgainstTimeout(update: Promise<void>, timeoutMs: number): Promise<UpdateOutcome> {
  return new Promise<UpdateOutcome>(resolve => {
    const timer = setTimeout(() => resolve({ kind: 'timeout' }), timeoutMs);
    update.then(
      () => {
        clearTimeout(timer);
        resolve({ kind: 'updated' });
      },
      (error: unknown) => {
        clearTimeout(timer);
        resolve({ kind: 'rejected', error });
      }
    );
  });
}

/**
 * The WebXR spec allows session.frameRate to keep its old value when
 * updateTargetFrameRate() resolves; the attribute change is only observable via a
 * later "frameratechange" event. Wait briefly for it so a stale value is not
 * advertised to CloudXR.
 */
function waitForReportedFrameRate(
  session: FrameRateSession,
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
 * Apply a headset frame rate and wait for the browser before CloudXR negotiates its stream.
 * Returns the effective rate to advertise to CloudXR, falling back without aborting the session.
 * A hung updateTargetFrameRate() must not block CloudXR session creation, so the wait is bounded.
 */
export async function applyTargetFrameRate(
  session: FrameRateSession,
  targetFrameRate: number,
  logger: FrameRateLogger = console,
  options: ApplyTargetFrameRateOptions = {}
): Promise<number> {
  const updateTimeoutMs = options.updateTimeoutMs ?? DEFAULT_UPDATE_TIMEOUT_MS;
  const rateSettleGraceMs = options.rateSettleGraceMs ?? DEFAULT_RATE_SETTLE_GRACE_MS;
  const currentFrameRate = isFinitePositive(session.frameRate) ? session.frameRate : undefined;

  if (!isFinitePositive(targetFrameRate)) {
    logger.warn('Ignoring invalid target WebXR frame rate:', targetFrameRate);
    return currentFrameRate ?? targetFrameRate;
  }

  if (!session.updateTargetFrameRate || !session.supportedFrameRates) {
    logger.warn(
      'WebXR target frame-rate API is unavailable; using the current/default frame rate:',
      currentFrameRate ?? targetFrameRate
    );
    return currentFrameRate ?? targetFrameRate;
  }

  if (!containsFrameRate(session.supportedFrameRates, targetFrameRate)) {
    logger.warn(
      'Requested WebXR frame rate is not supported by this device:',
      targetFrameRate
    );
    return currentFrameRate ?? targetFrameRate;
  }

  let update: Promise<void>;
  try {
    update = session.updateTargetFrameRate(targetFrameRate);
  } catch (error) {
    logger.warn('Failed to apply the requested WebXR frame rate:', targetFrameRate, error);
    return currentFrameRate ?? targetFrameRate;
  }

  const outcome = await raceUpdateAgainstTimeout(update, updateTimeoutMs);

  if (outcome.kind === 'timeout') {
    logger.warn(
      `updateTargetFrameRate(${targetFrameRate}) did not settle within ${updateTimeoutMs} ms; ` +
        'continuing so CloudXR negotiation is not blocked. Advertising the known rate:',
      currentFrameRate ?? targetFrameRate
    );
    return currentFrameRate ?? targetFrameRate;
  }

  if (outcome.kind === 'rejected') {
    logger.warn('Failed to apply the requested WebXR frame rate:', targetFrameRate, outcome.error);
    return currentFrameRate ?? targetFrameRate;
  }

  if (session.frameRate !== undefined && session.frameRate !== targetFrameRate) {
    await waitForReportedFrameRate(session, targetFrameRate, rateSettleGraceMs);
  }

  // A resolved updateTargetFrameRate() means the device accepted the rate change.
  // session.frameRate may lag behind the acceptance (it only settles with a later
  // frameratechange event), so the accepted target is the honest rate to advertise.
  if (session.frameRate !== undefined && session.frameRate !== targetFrameRate) {
    logger.warn(
      `Browser still reports ${session.frameRate} Hz after accepting ${targetFrameRate} Hz; ` +
        'advertising the accepted target to CloudXR.'
    );
  } else {
    logger.info('WebXR frame rate applied before CloudXR negotiation:', targetFrameRate);
  }
  return targetFrameRate;
}
