# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The renderer, driven without a browser.

Skips wherever viser is not installed, which includes CI: the panel is an optional
extra and the checker's own suite must not start needing it.
"""

from __future__ import annotations

import socket
from typing import Iterator

import pytest
import synth
from fullbody_acceptance.frames import NUM_JOINTS
from fullbody_acceptance.panel.track import TeeSource
from fullbody_acceptance.report import run

viser = pytest.importorskip("viser")

from fullbody_acceptance.panel.app import Panel  # noqa: E402  needs viser


def free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return int(probe.getsockname()[1])


@pytest.fixture
def server() -> Iterator["viser.ViserServer"]:
    running = viser.ViserServer(host="127.0.0.1", port=free_port(), verbose=False)
    yield running
    running.stop()


def panel_over(frames: list, server) -> Panel:
    source = TeeSource(synth.StubSource(frames))
    report = run(source)
    return Panel(server, report, source.track())


def test_a_take_plays_from_end_to_end(server):
    """Every sample goes through the draw path, including the joint that drops out."""
    frames = synth.frames(400) + synth.frames(400, valid_joints=NUM_JOINTS - 3)
    panel = panel_over(frames, server)
    panel._playing.value = True

    seen = set()
    for _ in range(2000):
        panel.advance(0.01)
        panel.draw_rate()
        seen.add(panel._index)
    assert len(seen) > 100


def test_a_recording_with_no_frames_still_builds(server):
    panel = panel_over([], server)
    panel._playing.value = True
    panel.advance(1.0)
    panel.draw_rate()


def test_seeking_by_hand_moves_the_playhead(server):
    panel = panel_over(synth.frames(200), server)
    panel._scrub.value = 150
    assert panel._index == 150
