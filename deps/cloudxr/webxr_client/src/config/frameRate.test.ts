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

import { applyTargetFrameRate, FrameRateLogger, FrameRateSession } from './frameRate';

const logger = (): jest.Mocked<FrameRateLogger> => ({
  info: jest.fn(),
  warn: jest.fn(),
});

describe('applyTargetFrameRate', () => {
  it('applies a supported rate and returns the effective rate', async () => {
    const session: FrameRateSession = {
      frameRate: 90,
      supportedFrameRates: new Float32Array([72, 90, 120]),
      updateTargetFrameRate: jest.fn(async rate => {
        session.frameRate = rate;
      }),
    };

    await expect(applyTargetFrameRate(session, 72, logger())).resolves.toBe(72);
    expect(session.updateTargetFrameRate).toHaveBeenCalledWith(72);
  });

  it('does not request an unsupported rate', async () => {
    const updateTargetFrameRate = jest.fn(async () => {});
    const session: FrameRateSession = {
      frameRate: 90,
      supportedFrameRates: new Float32Array([90, 120]),
      updateTargetFrameRate,
    };

    await expect(applyTargetFrameRate(session, 72, logger())).resolves.toBe(90);
    expect(updateTargetFrameRate).not.toHaveBeenCalled();
  });

  it('uses the current rate when the update API is unavailable', async () => {
    const session: FrameRateSession = { frameRate: 90 };

    await expect(applyTargetFrameRate(session, 72, logger())).resolves.toBe(90);
  });

  it('falls back to the current rate when the update is rejected', async () => {
    const session: FrameRateSession = {
      frameRate: 90,
      supportedFrameRates: new Float32Array([72, 90]),
      updateTargetFrameRate: jest.fn(async () => {
        throw new Error('headset rejected rate');
      }),
    };

    await expect(applyTargetFrameRate(session, 72, logger())).resolves.toBe(90);
  });

  it('does not resolve until the headset update has completed', async () => {
    let releaseUpdate!: () => void;
    const update = new Promise<void>(resolve => {
      releaseUpdate = resolve;
    });
    const session: FrameRateSession = {
      frameRate: 90,
      supportedFrameRates: new Float32Array([72, 90]),
      updateTargetFrameRate: jest.fn(() => update),
    };
    let completed = false;
    const applying = applyTargetFrameRate(session, 72, logger()).then(value => {
      completed = true;
      return value;
    });

    await Promise.resolve();
    expect(completed).toBe(false);
    session.frameRate = 72;
    releaseUpdate();
    await expect(applying).resolves.toBe(72);
  });

  it('does not block CloudXR when the update never settles', async () => {
    const log = logger();
    const session: FrameRateSession = {
      frameRate: 90,
      supportedFrameRates: new Float32Array([72, 90]),
      updateTargetFrameRate: jest.fn(() => new Promise<void>(() => {})),
    };

    await expect(
      applyTargetFrameRate(session, 72, log, { updateTimeoutMs: 20 })
    ).resolves.toBe(90);
    expect(log.warn).toHaveBeenCalled();
  });

  it('waits for frameratechange when the attribute updates late', async () => {
    const listeners: Array<() => void> = [];
    const removeEventListener = jest.fn();
    const session: FrameRateSession = {
      frameRate: 90,
      supportedFrameRates: new Float32Array([72, 90]),
      updateTargetFrameRate: jest.fn(async () => {
        setTimeout(() => {
          session.frameRate = 72;
          listeners.forEach(listener => listener());
        }, 5);
      }),
      addEventListener: jest.fn((_type, listener) => {
        listeners.push(listener);
      }),
      removeEventListener,
    };

    await expect(
      applyTargetFrameRate(session, 72, logger(), { rateSettleGraceMs: 200 })
    ).resolves.toBe(72);
    expect(removeEventListener).toHaveBeenCalledWith('frameratechange', expect.any(Function));
  });

  it('advertises the accepted target even when the attribute lags past the grace', async () => {
    const log = logger();
    const session: FrameRateSession = {
      frameRate: 90,
      supportedFrameRates: new Float32Array([72, 90]),
      updateTargetFrameRate: jest.fn(async () => {}),
      addEventListener: jest.fn(),
      removeEventListener: jest.fn(),
    };

    await expect(
      applyTargetFrameRate(session, 72, log, { rateSettleGraceMs: 10 })
    ).resolves.toBe(72);
    expect(log.warn).toHaveBeenCalled();
  });

  it('trusts the accepted request when the browser does not expose frameRate', async () => {
    const session: FrameRateSession = {
      supportedFrameRates: new Float32Array([72, 90]),
      updateTargetFrameRate: jest.fn(async () => {}),
    };

    await expect(applyTargetFrameRate(session, 72, logger())).resolves.toBe(72);
  });
});
