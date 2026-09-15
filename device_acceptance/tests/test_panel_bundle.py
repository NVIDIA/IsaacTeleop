# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The submission bundle. No viser: the archive is arithmetic, not rendering."""

from __future__ import annotations

import hashlib
import io
import json
import zipfile
from pathlib import Path

import pytest
import synth
from fullbody_acceptance.labels import StepTimeline
from fullbody_acceptance.panel import bundle
from fullbody_acceptance.panel.track import TeeSource
from fullbody_acceptance.report import run

LABELS = {
    "provisional": True,
    "nominal_rate_hz": 60.0,
    "steps": [
        {"index": 0, "label": "a_pose_still", "start_ns": 0, "end_ns": 1_000_000_000},
        {
            "index": 1,
            "label": "t_pose_hold_open",
            "start_ns": 1_000_000_000,
            "end_ns": 2_000_000_000,
        },
    ],
}


@pytest.fixture
def take(tmp_path: Path) -> Path:
    """A recording with the three companions a real capture leaves beside it."""
    recording = synth.write_recording(tmp_path / "145511-g4.mcap", synth.frames(120))
    recording.with_name("145511-g4.labels.json").write_text(json.dumps(LABELS))
    recording.with_name("145511-g4.json").write_text('{"device": "pico4u"}')
    recording.with_name("145511-g4.log").write_text("[record] writing 145511-g4.mcap\n")
    return recording


def packaged(recording: Path, timeline: StepTimeline | None = ..., **kwargs):
    """Runs the checks over frames in memory and packages them beside ``recording``."""
    if timeline is ...:
        timeline = StepTimeline.beside(recording)
    source = TeeSource(synth.StubSource(synth.frames(120)), timeline)
    report = run(source, None, timeline)
    name, data = bundle.build(report, source.track(), recording, timeline, **kwargs)
    return (name, data, report)


def members(data: bytes) -> dict[str, bytes]:
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return {name: archive.read(name) for name in archive.namelist()}


def test_the_archive_holds_the_take_its_companions_and_the_report(take):
    name, data, report = packaged(take)
    root = f"145511-g4.{report.verdict}"
    assert name == f"{root}.zip"
    # One top-level directory, so unzipping cannot spray files into a working dir.
    assert set(members(data)) == {
        f"{root}/145511-g4.mcap",
        f"{root}/145511-g4.labels.json",
        f"{root}/145511-g4.json",
        f"{root}/145511-g4.log",
        f"{root}/report.json",
        f"{root}/report.txt",
    }


def test_the_packed_recording_is_byte_for_byte_the_source(take):
    _, data, report = packaged(take)
    inside = members(data)
    packed = inside[f"145511-g4.{report.verdict}/145511-g4.mcap"]
    assert packed == take.read_bytes()

    payload = json.loads(inside[f"145511-g4.{report.verdict}/report.json"])
    entry = next(
        item for item in payload["inputs"]["files"] if item["name"].endswith(".mcap")
    )
    assert entry["sha256"] == hashlib.sha256(packed).hexdigest()
    assert entry["bytes"] == len(packed)


def test_report_json_survives_a_strict_parser(take):
    """A bare NaN is legal to `json` and fatal to `JSON.parse`, which reads this."""

    def refuse(constant: str) -> None:
        raise AssertionError(f"non-finite {constant} would break JSON.parse")

    _, data, report = packaged(take)
    raw = members(data)[f"145511-g4.{report.verdict}/report.json"]
    json.loads(raw, parse_constant=refuse)


def test_every_packed_mark_is_the_checkers_own(take):
    """The display layer cannot drift from the checker: one definition, carried."""
    _, data, report = packaged(take)
    payload = json.loads(members(data)[f"145511-g4.{report.verdict}/report.json"])
    assert {check["name"]: check["mark"] for check in payload["checks"]} == {
        result.name: str(result.mark) for result in report.results
    }


def test_the_groups_name_every_packed_check_once(take):
    _, data, report = packaged(take)
    payload = json.loads(members(data)[f"145511-g4.{report.verdict}/report.json"])
    grouped = [name for group in payload["groups"] for name in group["checks"]]
    assert sorted(grouped) == sorted(check["name"] for check in payload["checks"])


def test_the_series_carries_every_frame_and_nulls_a_rate_it_cannot_state(take):
    _, data, report = packaged(take)
    payload = json.loads(members(data)[f"145511-g4.{report.verdict}/report.json"])
    series = payload["series"]
    assert len(series["t_ms"]) == len(series["rate_hz"]) == report.frames
    # The first frame has no interval to divide, so it has no rate.
    assert series["rate_hz"][0] is None
    assert series["rate_hz"][1] is not None


def test_a_take_with_no_labels_says_which_input_is_missing(take):
    take.with_name("145511-g4.labels.json").unlink()
    _, data, report = packaged(take, timeline=None)
    payload = json.loads(members(data)[f"145511-g4.{report.verdict}/report.json"])
    assert payload["inputs"]["missing"] == ["145511-g4.labels.json"]
    assert payload["inputs"]["labels"] == {
        "present": False,
        "provisional": None,
        "steps": None,
        "source": None,
    }


def test_labels_read_from_elsewhere_are_packed_from_where_they_were_read(
    take, tmp_path
):
    """`--labels` elsewhere must not leave the verdict's own labels out of the zip."""
    take.with_name("145511-g4.labels.json").unlink()
    elsewhere = tmp_path / "moved" / "session.labels.json"
    elsewhere.parent.mkdir()
    elsewhere.write_text(json.dumps(LABELS))

    _, data, report = packaged(take, timeline=StepTimeline.load(elsewhere))
    root = f"145511-g4.{report.verdict}"
    assert f"{root}/session.labels.json" in members(data)
    payload = json.loads(members(data)[f"{root}/report.json"])
    assert payload["inputs"]["labels"] == {
        "present": True,
        "provisional": True,
        "steps": 2,
        "source": "session.labels.json",
    }


def test_progress_runs_forward_and_finishes(take):
    seen: list[float] = []
    packaged(take, on_progress=seen.append)
    assert seen == sorted(seen)
    assert seen[-1] == 1.0
    assert min(seen) > 0.0


def test_two_builds_of_one_take_agree(take):
    """The checker is deterministic, so the manifest has to be too."""
    _, first, report = packaged(take)
    _, second, _ = packaged(take)
    name = f"145511-g4.{report.verdict}/report.json"
    # The zip bytes differ by member mtime; the contents must not.
    assert members(first)[name] == members(second)[name]


def test_the_tool_block_names_the_checker_that_ran(take):
    _, data, report = packaged(take)
    payload = json.loads(members(data)[f"145511-g4.{report.verdict}/report.json"])
    tool = payload["tool"]
    assert tool["checks"] == len(report.results)
    # Null where git cannot answer, which is a submitter working from an archive.
    assert tool["commit"] is None or len(tool["commit"]) == 40
    assert tool["dirty"] in (True, False, None)


def test_a_report_with_no_results_still_packages(take):
    """An empty report has no groups and no worst mark; neither may raise."""
    source = TeeSource(synth.StubSource([]))
    empty = run(source, [], None)
    _, data = bundle.build(empty, source.track(), take)
    payload = json.loads(members(data)[f"145511-g4.{empty.verdict}/report.json"])
    assert payload["groups"] == []
    assert payload["series"]["t_ms"] == []
