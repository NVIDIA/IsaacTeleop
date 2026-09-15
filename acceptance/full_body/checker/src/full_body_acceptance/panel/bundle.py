# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""One archive holding a take and everything needed to judge it again.

Standard library only, like everything here except ``app.py``.

zip rather than tar.gz, though both are DEFLATE and measure the same (4.42 MB in
0.17 s on a 7.27 MB take): the central directory reads ``report.json`` out in 0.4 ms,
against 17.4 ms to merely *list* a tar.gz, whose whole stream must be decompressed to
reach the last member. Triaging a mailbox of submissions then never touches the MCAP.
Recorder output is uncompressed, so deflate is worth its 0.17 s — 7.27 MB to 4.42 MB.
"""

from __future__ import annotations

import hashlib
import io
import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

from ..labels import SIDECAR_SUFFIX, StepTimeline
from ..report import Report
from . import status
from .track import Track

CHUNK = 1 << 20

# Beside the recording, and not derivable from it: capture provenance and the recorder
# log. The labels sidecar is the load-bearing one — without it every G4 check reports
# unanswered and the verdict changes — so it is fetched separately, from the timeline
# that was actually used rather than by name.
PROVENANCE_SUFFIXES = (".json", ".log")


def build(
    report: Report,
    track: Track,
    recording: Path | str,
    timeline: StepTimeline | None = None,
    on_progress: Callable[[float], None] | None = None,
) -> tuple[str, bytes]:
    """The archive's filename and its bytes. ``on_progress`` is called with 0.0–1.0.

    Everything sits under one directory, so unzipping cannot spray files into the
    reader's working directory.
    """
    recording = Path(recording)
    present, missing = companions(recording, timeline)
    packed = [recording, *present]
    total = sum(path.stat().st_size for path in packed) or 1
    root = archive_stem(recording, report)

    buffer = io.BytesIO()
    done = 0
    files: list[dict[str, Any]] = []
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in packed:
            digest = hashlib.sha256()
            size = 0
            with archive.open(f"{root}/{path.name}", "w") as member:
                with path.open("rb") as source:
                    while chunk := source.read(CHUNK):
                        member.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                        done += len(chunk)
                        if on_progress is not None:
                            on_progress(min(done / total, 1.0))
            files.append(
                {"name": path.name, "bytes": size, "sha256": digest.hexdigest()}
            )
        payload = manifest(report, track, timeline, files, missing)
        archive.writestr(
            f"{root}/report.json", json.dumps(payload, indent=2, allow_nan=False)
        )
        archive.writestr(f"{root}/report.txt", report.to_text())
    if on_progress is not None:
        on_progress(1.0)
    return (f"{root}.zip", buffer.getvalue())


def manifest(
    report: Report,
    track: Track,
    timeline: StepTimeline | None,
    files: Sequence[dict[str, Any]],
    missing: Iterable[str],
) -> dict[str, Any]:
    """``report.to_dict()`` plus what a reader holding only this archive needs.

    Inputs and outputs are kept apart because the checker is deterministic: the same
    recording run twice gives byte-identical output, so the results here are a cache
    and the recording is the evidence. Where a re-run disagrees, the recording wins.

    ``groups`` comes from ``status`` rather than being defined again, so a dashboard
    reading this file needs no acceptance logic of its own — the same reason each
    check already carries its ``mark``.
    """
    return {
        "tool": tool(len(report.results)),
        "inputs": {
            "files": list(files),
            "labels": _labels(timeline),
            "missing": list(missing),
        },
        **report.to_dict(),
        "groups": [
            {
                "code": gate.code,
                "title": gate.title,
                "checks": [result.name for result in gate.results],
            }
            for gate in status.gates(report)
        ],
        "series": series(track),
    }


def series(track: Track) -> dict[str, list[Any]]:
    """Frame rate and valid-joint count against time, columnar.

    Columnar because it is smaller than a list of records and because it is the shape
    uPlot consumes directly. Every frame is kept: 5757 of them cost 15 KB deflated
    beside a recording of several megabytes, and decimation is exactly what erases the
    dropped-frame spike the curve exists to show.

    A rate that does not exist is ``null``, not NaN: ``json`` writes a bare ``NaN``
    that ``JSON.parse`` rejects, and ``allow_nan=False`` in ``build`` is the guard.
    """
    samples = track.samples
    return {
        "t_ms": [round(sample.t_s * 1000.0, 1) for sample in samples],
        "rate_hz": [
            None if sample.rate_hz != sample.rate_hz else round(sample.rate_hz, 2)
            for sample in samples
        ],
        "valid": [sample.valid_count for sample in samples],
    }


def archive_stem(report_recording: Path, report: Report) -> str:
    """``<device>_<date>_<take>.<verdict>``.

    The take name is a time of day, so it repeats every day and collides outright
    between two devices recording at once. The verdict is in there so a mailbox of
    submissions can be triaged without opening any of them.
    """
    device, date = capture_identity(report_recording)
    named = "_".join(part for part in (device, date, report_recording.stem) if part)
    return f"{named}.{report.verdict}"


def capture_identity(recording: Path) -> tuple[str, str]:
    """Device and date, from the capture sidecar and then from the layout.

    ``record.sh`` writes both by construction — ``<device>/<date>/<time>-g4.mcap``
    on disk, and the same two strings into ``<take>.json`` — so they agree wherever
    both exist. The sidecar is the one that says which is which, so it answers first;
    the path covers a take whose sidecar never arrived or that was copied elsewhere.
    """
    device = date = ""
    try:
        payload = json.loads(recording.with_name(recording.stem + ".json").read_text())
    except (OSError, ValueError):
        payload = {}
    if isinstance(payload, dict):
        device = str(payload.get("device") or "")
        date = str(payload.get("recorded_at") or "")[:10]
    if not (device and date):
        holder = recording.resolve().parent
        device = device or holder.parent.name
        date = date or holder.name
    return (_filename_safe(device), _filename_safe(date))


def companions(
    recording: Path, timeline: StepTimeline | None = None
) -> tuple[list[Path], list[str]]:
    """Which files beside the recording exist, and the names of those that do not.

    A missing companion is not an error — a recording without labels is a supported
    case — but it has to be said out loud, or a reader seeing every G4 check
    unanswered reads a missing input as a broken checker.
    """
    labels = (
        Path(timeline.source)
        if timeline is not None and timeline.source
        else recording.with_name(recording.stem + SIDECAR_SUFFIX)
    )
    wanted = [labels] + [
        recording.with_name(recording.stem + suffix) for suffix in PROVENANCE_SUFFIXES
    ]
    return (
        [path for path in wanted if path.is_file()],
        [path.name for path in wanted if not path.is_file()],
    )


def tool(checks: int) -> dict[str, Any]:
    """Which checker produced this, so a later re-run that disagrees is legible.

    Reproducibility holds at one commit. Without this, a disagreement cannot be told
    apart from the submitter never having run the checker at all.

    ``dirty`` covers the package only; nothing else in the repository can change a
    verdict. Both are null where git cannot answer, which is the case for a submitter
    working from an archive rather than a clone.
    """
    package = Path(__file__).resolve().parent.parent
    changed = _git(package, "status", "--porcelain", "--", str(package))
    return {
        "commit": _git(package, "rev-parse", "HEAD"),
        "dirty": None if changed is None else bool(changed),
        "checks": checks,
    }


def _filename_safe(text: str) -> str:
    """The device name reaches here from a shell argument and becomes a filename."""
    return "".join(c if c.isalnum() or c in "-." else "_" for c in text).strip("_.")


def _labels(timeline: StepTimeline | None) -> dict[str, Any]:
    """Fixed keys whether or not there were labels, so a reader needs no branch."""
    if timeline is None:
        return {"present": False, "provisional": None, "steps": None, "source": None}
    return {
        "present": True,
        "provisional": timeline.provisional,
        "steps": len(timeline.steps),
        "source": Path(timeline.source).name if timeline.source else None,
    }


def _git(cwd: Path, *args: str) -> str | None:
    try:
        done = subprocess.run(
            ("git", "-C", str(cwd), *args),
            capture_output=True,
            text=True,
            timeout=5.0,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.strip() if done.returncode == 0 else None
