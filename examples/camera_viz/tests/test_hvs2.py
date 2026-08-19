# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0
"""HVS2 record framing: argus_sender's stereo wire format."""

from __future__ import annotations

import io
import struct

import pytest

from sources.hvs2 import read_records, split_streams

_HDR = struct.Struct(">4sHHQII")


def _record(seq: int, left: bytes, right: bytes, magic=b"HVS2", version=1) -> bytes:
    payload = _HDR.pack(magic, version, 0, seq, len(left), len(right)) + left + right
    return struct.pack(">I", len(payload)) + payload


def test_reads_a_pair():
    (rec,) = list(read_records(io.BytesIO(_record(1, b"LLL", b"RRRR"))))
    assert (rec.sequence, rec.left, rec.right) == (1, b"LLL", b"RRRR")


def test_reads_a_run_in_order():
    blob = b"".join(_record(i, bytes([i]) * 3, bytes([i]) * 5) for i in (1, 2, 3))
    assert [r.sequence for r in read_records(io.BytesIO(blob))] == [1, 2, 3]


def test_a_torn_final_record_ends_the_stream_quietly():
    """An abrupt sender shutdown leaves a partial record; a half-written pair
    is not a reason to fail a replay."""
    blob = _record(1, b"LL", b"RR") + _record(2, b"LL", b"RR")[:-3]
    assert [r.sequence for r in read_records(io.BytesIO(blob))] == [1]


def test_a_truncated_length_prefix_ends_the_stream_quietly():
    """The records before the torn tail still come through."""
    blob = _record(1, b"L", b"R") + b"\x00\x00"
    assert [r.sequence for r in read_records(io.BytesIO(blob))] == [1]


def test_a_sequence_restart_is_not_an_error():
    """argus_sender rebuilds the pipeline when a receiver reconnects and
    appends the next session to the same file, restarting at 1."""
    blob = _record(1, b"L", b"R") + _record(2, b"L", b"R") + _record(1, b"L", b"R")
    assert [r.sequence for r in read_records(io.BytesIO(blob))] == [1, 2, 1]


def test_bad_magic_raises():
    with pytest.raises(ValueError, match="bad HVS2 magic"):
        list(read_records(io.BytesIO(_record(1, b"L", b"R", magic=b"XXXX"))))


def test_unsupported_version_raises():
    with pytest.raises(ValueError, match="unsupported HVS2 version"):
        list(read_records(io.BytesIO(_record(1, b"L", b"R", version=2))))


def test_inconsistent_lengths_raise():
    """record_length must equal 24 + left + right; a complete record that
    disagrees is corrupt, not merely torn."""
    payload = _HDR.pack(b"HVS2", 1, 0, 7, 99, 99) + b"LL" + b"RR"
    blob = struct.pack(">I", len(payload)) + payload
    with pytest.raises(ValueError, match="length"):
        list(read_records(io.BytesIO(blob)))


def test_split_streams_preserves_record_order(tmp_path):
    src = tmp_path / "in.hvs2"
    src.write_bytes(b"".join(_record(i, b"L%d" % i, b"R%d" % i) for i in (1, 2, 3)))
    left, right = tmp_path / "l.h265", tmp_path / "r.h265"
    assert split_streams(src, left, right) == 3
    assert left.read_bytes() == b"L1L2L3"
    assert right.read_bytes() == b"R1R2R3"


def test_a_tilde_path_is_expanded():
    """`~` is the shell's job, and nothing expanded it here: Path("~/x") is a
    literal directory named "~"."""
    from sources import resolve_video_paths

    cfg = {"cameras": [{"name": "c", "type": "hvs2", "path": "~/clip.hvs2"}]}
    resolve_video_paths(cfg, "/base")
    assert not cfg["cameras"][0]["path"].startswith("~")


def test_a_relative_path_is_anchored_to_the_config_dir():
    from sources import resolve_video_paths

    cfg = {"cameras": [{"name": "c", "type": "hvs2", "path": "clips/a.hvs2"}]}
    resolve_video_paths(cfg, "/base")
    assert cfg["cameras"][0]["path"] == "/base/clips/a.hvs2"


def test_source_construction_probes_the_real_clip():
    """Constructing the source is what caught a SourceSpec signature mismatch
    that no parser test could: the coded size comes from the stream, so this
    exercises probe + spec together."""
    import os
    from pathlib import Path

    clip = Path.home() / "Downloads" / "shw5g_stereo.hvs2"
    if not clip.is_file():
        pytest.skip("no HVS2 capture on this machine")
    if os.environ.get("CI"):
        pytest.skip("decodes a frame; not for CI")
    from sources.hvs2 import Hvs2Source

    spec = Hvs2Source(clip, name="hvs2").spec
    assert (spec.width, spec.height) == (2560, 1984)
    assert spec.pixel_format == "rgba8"
