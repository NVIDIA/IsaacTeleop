# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Speaks the G4 motion script to a performer who is wearing the headset.

The cues are WAV files in `cues/`, rendered once by piper and committed. Nothing is
synthesised at run time, and the synthesiser is not a dependency of recording a take.
Each cue is scheduled to *finish* as its window opens, so the performer moves during
the leading part of the window that the posture checks discard anyway
(SETTLE_FRACTION = 0.40).

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
import hashlib
import json
import subprocess
import sys
import time
import wave
from pathlib import Path

from session import BRIEFING, LEAD_IN_S, STEPS, STILL_LABELS, total_duration_s

HERE = Path(__file__).resolve().parent
CUES = HERE / "cues"

GAP_S = 0.15  # silence between a cue ending and its window opening
HOLD_WARNING_S = 1.0  # how long before a held window ends the tick sounds

CLOSING = "Done. You can stop now."


def cue(label: str, text: str) -> Path:
    """The recorded WAV for one cue, refusing a file that says something else.

    `cues/index.json` holds the hash of the text each WAV was rendered from, so
    rewording a cue in session.py stops the run here instead of playing the old
    wording at a performer who cannot tell.
    """
    index = json.loads((CUES / "index.json").read_text())
    recorded = index["text_sha1"].get(label)
    current = hashlib.sha1(text.encode()).hexdigest()[:16]
    if recorded is None:
        raise SystemExit(f"{CUES}/index.json has no cue named {label!r}")
    if recorded != current:
        raise SystemExit(
            f"the wording of cue {label!r} changed, so {label}.wav no longer says it:\n"
            f"  now: {text!r}\n"
            f"re-render it with piper at voice {index['voice']} and length scale "
            f"{index['length_scale']}, then update index.json"
        )
    return CUES / f"{label}.wav"


def duration_of(wav: Path) -> float:
    with wave.open(str(wav)) as handle:
        return handle.getnframes() / handle.getframerate()


def play(wav: Path) -> None:
    subprocess.Popen(
        ["aplay", "-q", str(wav)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
    )


def build_schedule() -> list[tuple[float, Path, str]]:
    """Returns (when_s, wav, log line) for every sound, in time order."""
    beep = CUES / "beep.wav"
    tick = CUES / "tick.wav"

    # Window bounds and the cue that opens each one, laid out first so the hold
    # ticks can be placed in the gaps rather than on top of the next instruction.
    opens, at = [], LEAD_IN_S
    for index, (label, duration, text) in enumerate(STEPS):
        wav = cue(label, text)
        opens.append(
            {
                "index": index,
                "label": label,
                "cue": text,
                "wav": wav,
                "start": at,
                "end": at + duration,
                "cue_at": at - duration_of(wav) - GAP_S,
            }
        )
        at += duration
    script_end = at

    events: list[tuple[float, Path, str]] = [
        (0.0, cue("briefing", BRIEFING), "briefing"),
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
    events.append((script_end + 0.3, cue("closing", CLOSING), "done"))
    return sorted(events, key=lambda event: event[0])


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--rehearse",
        action="store_true",
        help="run the cues without expecting a recorder",
    )
    args = parser.parse_args()

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
