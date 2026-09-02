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

import { recordingCueTonePattern } from './recordingCue';

describe('recordingCueTonePattern', () => {
  it('uses an ascending two-note cue when recording starts', () => {
    const tones = recordingCueTonePattern({ state: 'recording' });
    expect(tones).toHaveLength(2);
    expect(tones[1].frequencyHz).toBeGreaterThan(tones[0].frequencyHz);
  });

  it('uses distinct completion patterns for each outcome', () => {
    const success = recordingCueTonePattern({ state: 'stopped', outcome: 'success' });
    const failure = recordingCueTonePattern({ state: 'stopped', outcome: 'failure' });
    const unknown = recordingCueTonePattern({ state: 'stopped', outcome: 'unknown' });

    expect(success).not.toEqual(failure);
    expect(failure).not.toEqual(unknown);
    expect(unknown).not.toEqual(success);
  });
});
