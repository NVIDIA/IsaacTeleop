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

import type { RecordingStatus } from './types/serverMessages';

export interface RecordingCueTone {
  frequencyHz: number;
  startsAfterMs: number;
  durationMs: number;
}

/** Distinct short patterns for start and each end outcome. */
export function recordingCueTonePattern(status: RecordingStatus): readonly RecordingCueTone[] {
  if (status.state === 'recording') {
    return [
      { frequencyHz: 660, startsAfterMs: 0, durationMs: 80 },
      { frequencyHz: 880, startsAfterMs: 95, durationMs: 110 },
    ];
  }
  if (status.outcome === 'success') {
    return [
      { frequencyHz: 880, startsAfterMs: 0, durationMs: 90 },
      { frequencyHz: 1100, startsAfterMs: 105, durationMs: 140 },
    ];
  }
  if (status.outcome === 'failure') {
    return [
      { frequencyHz: 440, startsAfterMs: 0, durationMs: 120 },
      { frequencyHz: 294, startsAfterMs: 135, durationMs: 180 },
    ];
  }
  return [{ frequencyHz: 550, startsAfterMs: 0, durationMs: 180 }];
}

type WebkitAudioWindow = Window & { webkitAudioContext?: typeof AudioContext };

let audioContext: AudioContext | null = null;

function getAudioContext(): AudioContext | null {
  if (audioContext !== null) return audioContext;
  const AudioContextConstructor =
    window.AudioContext ?? (window as WebkitAudioWindow).webkitAudioContext;
  if (!AudioContextConstructor) return null;
  audioContext = new AudioContextConstructor();
  return audioContext;
}

/** Unlock Web Audio from the explicit Connect gesture before asynchronous cues arrive. */
export async function primeRecordingCueAudio(): Promise<void> {
  const context = getAudioContext();
  if (context?.state === 'suspended') await context.resume();
}

/** Play a recording cue locally on the headset. */
export async function playRecordingCueSound(status: RecordingStatus): Promise<void> {
  try {
    const context = getAudioContext();
    if (context === null) return;
    if (context.state === 'suspended') await context.resume();

    const baseTime = context.currentTime;
    for (const tone of recordingCueTonePattern(status)) {
      const startTime = baseTime + tone.startsAfterMs / 1000;
      const endTime = startTime + tone.durationMs / 1000;
      const oscillator = context.createOscillator();
      const gain = context.createGain();
      oscillator.type = 'sine';
      oscillator.frequency.setValueAtTime(tone.frequencyHz, startTime);
      gain.gain.setValueAtTime(0, startTime);
      gain.gain.linearRampToValueAtTime(0.16, startTime + 0.01);
      gain.gain.linearRampToValueAtTime(0, endTime);
      oscillator.connect(gain);
      gain.connect(context.destination);
      oscillator.start(startTime);
      oscillator.stop(endTime);
    }
  } catch (error) {
    console.warn('Unable to play recording cue:', error);
  }
}
