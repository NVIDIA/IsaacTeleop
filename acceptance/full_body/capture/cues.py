# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The spoken cues and the two window tones, played through ``aplay``.

The WAVs in ``cues/`` were rendered once by piper and committed. Nothing is synthesised
at run time, and the synthesiser is not a dependency of recording a take.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import wave
from pathlib import Path

HERE = Path(__file__).resolve().parent
CUES = HERE / "cues"

# A window's two boundaries must not sound the same, or the performer cannot tell the
# pose starting from the pose ending. These are the two committed tones.
START_TONE = CUES / "beep.wav"
END_TONE = CUES / "tick.wav"

#: The one spoken line that is not a step, played once the file is closed.
CLOSING = "Done. You can stop now."


def wav(label: str, text: str) -> Path:
    """The recorded WAV for one cue, refusing a file that says something else.

    ``cues/index.json`` holds the hash of the text each WAV was rendered from, so
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


def duration_of(path: Path) -> float:
    with wave.open(str(path)) as handle:
        return handle.getnframes() / handle.getframerate()


def play(path: Path) -> subprocess.Popen:
    """Start a sound and return without waiting for it.

    The handle comes back so a spoken cue can be cut short when the performer presses
    during it; nothing ever waits on the exit status.
    """
    return subprocess.Popen(
        ["aplay", "-q", str(path)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
