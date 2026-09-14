# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Shapes the Pico tracker produces that the shared fixture set does not cover.

The fixture set's benign cases are modelled on the Noitom plugin. Pico differs in two
ways that would each make a naively-written checker reject working hardware, so they are
covered here and go through a real MCAP to exercise the reader as well.
"""

from __future__ import annotations

import synth

from fullbody_acceptance import McapFrameSource, run
from fullbody_acceptance.report import Verdict


def test_invalid_joints_may_carry_arbitrary_values(tmp_path):
    """Pico copies the OpenXR pose through whatever the location flags say.

    ``live_full_body_tracker_pico_impl.cpp`` assigns position and orientation
    unconditionally and only then derives ``is_valid`` from
    ``XR_SPACE_LOCATION_POSITION_VALID_BIT`` and its orientation counterpart, so an
    invalid joint holds whatever the runtime left there. Noitom zeroes it instead, and a
    checker built only against that behaviour fails Pico.
    """
    garbage = [
        synth.joint(
            position=(float("nan"), float("inf"), -0.0),
            orientation=(9.0, -3.0, 0.5, 0.0),
            is_valid=False,
        ),
        synth.joint(
            position=(0.0, 0.0, 0.0), orientation=(0.0, 0.0, 0.0, 0.0), is_valid=False
        ),
        synth.joint(
            position=(1e9, -1e9, 7.0), orientation=(0.0, 0.0, 0.0, 12.0), is_valid=False
        ),
    ]
    frame_list = []
    for i in range(40):
        item = synth.frame(i)
        for offset, bad in enumerate(garbage):
            item = synth.with_joint(item, 10 + offset, bad)
        frame_list.append(item)

    path = synth.write_recording(tmp_path / "pico_invalid_garbage.mcap", frame_list)
    report = run(McapFrameSource(path))

    assert report.verdict is Verdict.PASS, report.to_text()
    assert report.failures == ()


def test_registered_channel_with_no_messages_cannot_conclude(tmp_path):
    """Limp mode leaves the channel registered and empty.

    When the runtime reports no body-tracking support the Pico tracker logs "running in
    limp mode" and returns from ``update()`` before ``publish_and_record``, so the
    channels created at construction never receive a message. Reading that as a pass
    would accept an integration that produced nothing at all.
    """
    path = synth.write_recording(tmp_path / "pico_limp_mode.mcap", [])
    source = McapFrameSource(path)

    assert source.metadata.channel_found is True
    assert list(source) == []

    report = run(source)
    assert report.verdict is Verdict.INSUFFICIENT_DATA
    assert any("limp mode" in note for note in report.notes)


def test_a_file_without_the_full_body_schema_is_not_a_pass(tmp_path):
    path = synth.write_recording(
        tmp_path / "other_schema.mcap",
        synth.frames(5),
        schema_name="core.HandPoseRecord",
        topic="hand/hand",
    )
    report = run(McapFrameSource(path))

    assert report.metadata.channel_found is False
    assert report.verdict is Verdict.INSUFFICIENT_DATA
    assert any("no channel declares" in note for note in report.notes)


def test_channel_is_located_by_schema_name_not_topic(tmp_path):
    """The topic prefix is whatever ``name=`` the recording script passed."""
    path = synth.write_recording(
        tmp_path / "renamed_topic.mcap",
        synth.frames(30),
        topic="vendor_xyz_body/full_body",
    )
    report = run(McapFrameSource(path))

    assert report.metadata.topic == "vendor_xyz_body/full_body"
    assert report.frames == 30
    assert report.verdict is Verdict.PASS
