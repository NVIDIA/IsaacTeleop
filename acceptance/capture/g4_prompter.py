# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Speaks the G4 motion script to a performer who is wearing the headset.

Cues are rendered to WAV once and cached; synthesising during the run would put a
variable delay in front of every window. Each cue is scheduled to *finish* as its
window opens, so the performer moves during the leading part of the window that the
posture checks discard anyway (SETTLE_FRACTION = 0.40).

Two tones carry the timing the speech cannot. A beep marks every window boundary, and
a held pose gets a soft tick meaning "still holding" -- never a release, since the
trailing 60% of that window is the measurement. The tick lands just before the next
instruction rather than near the end of the hold, because the next instruction is
what tempts the performer to move early, and on a 5 s hold it arrives halfway in.

Timing here only has to be good enough to follow. The labels are anchored to the clap
found in the recording, not to this process's clock.
"""

from __future__ import annotations

import argparse
import array
import hashlib
import math
import subprocess
import sys
import time
import wave
from pathlib import Path

from g4_session import BRIEFING, LEAD_IN_S, STEPS, STILL_LABELS, total_duration_s

HERE = Path(__file__).resolve().parent
VOICE = HERE / "tts_voices" / "en_GB-alba-medium.onnx"
PIPER = HERE / ".venv-tts" / "bin" / "piper"
CACHE = HERE / "tts_cache"

LENGTH_SCALE = "1.25"
GAP_S = 0.15  # silence between a cue ending and its window opening
HOLD_WARNING_S = 1.0  # how long before a held window ends the tick sounds

CLOSING = "Done. You can stop now."


def tone(path: Path, hz: float, seconds: float, volume: float) -> Path:
    """Writes a short sine beep with a raised-cosine envelope, so it does not click."""
    if path.is_file():
        return path
    rate = 22050
    total = int(rate * seconds)
    edge = max(1, int(rate * 0.008))
    samples = array.array("h")
    for n in range(total):
        gain = 1.0
        if n < edge:
            gain = 0.5 - 0.5 * math.cos(math.pi * n / edge)
        elif n > total - edge:
            gain = 0.5 - 0.5 * math.cos(math.pi * (total - n) / edge)
        samples.append(
            int(32767 * volume * gain * math.sin(2 * math.pi * hz * n / rate))
        )
    with wave.open(str(path), "w") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(samples.tobytes())
    return path


def render(text: str) -> Path:
    """Returns a cached WAV of `text`, synthesising it on first use.

    Synthesis happens before the run starts, so a cold cache is a silent minute with
    nothing on stdout unless it says so -- which reads as a dead script.
    """
    CACHE.mkdir(exist_ok=True)
    key = hashlib.sha1(f"{VOICE.stem}:{LENGTH_SCALE}:{text}".encode()).hexdigest()[:16]
    wav = CACHE / f"{key}.wav"
    if not wav.is_file():
        print(f"  synthesising: {text[:56]}", flush=True)
        subprocess.run(
            [
                str(PIPER),
                "-m",
                str(VOICE),
                "--length-scale",
                LENGTH_SCALE,
                "-f",
                str(wav),
            ],
            input=text.encode(),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    return wav


def duration_of(wav: Path) -> float:
    with wave.open(str(wav)) as handle:
        return handle.getnframes() / handle.getframerate()


def play(wav: Path) -> None:
    subprocess.Popen(
        ["aplay", "-q", str(wav)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def build_schedule() -> list[tuple[float, Path, str]]:
    """Returns (when_s, wav, log line) for every sound, in time order."""
    CACHE.mkdir(exist_ok=True)
    beep = tone(CACHE / "beep.wav", 880.0, 0.12, 0.45)
    tick = tone(CACHE / "tick.wav", 440.0, 0.08, 0.22)

    # Window bounds and the cue that opens each one, laid out first so the hold
    # ticks can be placed in the gaps rather than on top of the next instruction.
    opens, at = [], LEAD_IN_S
    for index, (label, duration, cue) in enumerate(STEPS):
        wav = render(cue)
        opens.append(
            {
                "index": index,
                "label": label,
                "cue": cue,
                "wav": wav,
                "start": at,
                "end": at + duration,
                "cue_at": at - duration_of(wav) - GAP_S,
            }
        )
        at += duration
    script_end = at

    events: list[tuple[float, Path, str]] = [
        (0.0, render(BRIEFING), "briefing"),
    ]
    for position, window in enumerate(opens):
        events.append(
            (
                window["cue_at"],
                window["wav"],
                f"{window['index']:2d} {window['label']}  {window['cue']}",
            )
        )
        events.append((window["start"], beep, f"   -> {window['label']} opens"))
        if window["label"] not in STILL_LABELS:
            continue
        # "Nearly there", so it has to land before the next instruction starts.
        following = opens[position + 1]["cue_at"] if position + 1 < len(opens) else None
        when = window["end"] - HOLD_WARNING_S
        if following is not None:
            when = min(when, following - 0.25)
        if when > window["start"] + 1.0:
            events.append((when, tick, "   (keep holding)"))

    events.append((script_end, beep, "   -> script ends"))
    events.append((script_end + 0.3, render(CLOSING), "done"))
    return sorted(events, key=lambda event: event[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rehearse",
        action="store_true",
        help="run the cues without expecting a recorder",
    )
    args = parser.parse_args()

    if not VOICE.is_file() or not PIPER.is_file():
        print(f"missing piper or the voice model under {HERE}", file=sys.stderr)
        return 1

    print("preparing cues", flush=True)
    schedule = build_schedule()
    print(
        f"lead-in {LEAD_IN_S:.0f} s, script {total_duration_s() - LEAD_IN_S:.0f} s, "
        f"total {total_duration_s():.0f} s"
        + ("   [rehearsal: nothing is recorded]" if args.rehearse else ""),
        flush=True,
    )
    print(flush=True)

    start = time.monotonic()
    for when, wav, line in schedule:
        while time.monotonic() - start < when:
            time.sleep(0.01)
        play(wav)
        print(f"  {time.monotonic() - start:5.1f}s  {line}", flush=True)
    time.sleep(1.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
