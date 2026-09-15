# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Which results the panel puts first, and how the rest group.

The text report already lists all 38 checks, and moving 38 lines onto a web page buys
nothing. What it cannot do is order them by what would make a take worth discarding, so
that ordering lives here.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from ..report import CheckResult, Mark, Report

# Worst first, and it is an order of claims rather than of severities: a failure beats
# an unanswered check, which beats a number nobody judged, which beats an advisory.
WORST_FIRST = (Mark.FAIL, Mark.UNANSWERED, Mark.MEAS, Mark.NOTE, Mark.PASS)

# The few results that decide whether the rest of the report is worth reading at all.
# Joint validity first: a take whose joints were never valid is void whatever else it
# says. Then rate, because dropped frames make every derivative meaningless. Then the
# coordinate conventions, which are one-off facts that leave every downstream number
# wrong while looking entirely plausible.
DECISIVE = (
    "coverage.payload_presence_rate",
    "coverage.validity_trend",
    "rate.interval_regularity",
    "rate.frame_gaps",
    "coordinate_frame.up_axis",
    "coordinate_frame.handedness",
    "skeleton.left_right_labelling",
    "units.position_scale_metres",
    "skeleton.bone_length_constancy",
)

GATE_TITLES: tuple[tuple[str, str, str], ...] = (
    ("G0", "Build and skip", "attested by the submitter"),
    ("G1", "Schema, envelope and signal quality", ""),
    ("G2", "Skeleton geometry", ""),
    ("G3", "Signal quality", "its checks report under G1"),
    ("G4", "Posture over the labelled windows", ""),
    ("G5", "Replay through retargeting", "not implemented"),
    ("G6", "Human review", "not automated, by design"),
)


@dataclass(frozen=True, slots=True)
class Gate:
    code: str
    title: str
    absent: str
    results: tuple[CheckResult, ...]

    @property
    def mark(self) -> Mark | None:
        """The worst mark in the gate, or None when no check here answers to it."""
        return min((r.mark for r in self.results), key=WORST_FIRST.index, default=None)

    @property
    def tally(self) -> str:
        counts = Counter(r.mark for r in self.results)
        return ", ".join(
            f"{counts[mark]} {mark}" for mark in WORST_FIRST if counts[mark]
        )


def worst_first(results: tuple[CheckResult, ...]) -> tuple[CheckResult, ...]:
    """Stable, so results keep the report's dependency order inside one mark."""
    return tuple(sorted(results, key=lambda r: WORST_FIRST.index(r.mark)))


def gates(report: Report) -> tuple[Gate, ...]:
    grouped: dict[str, list[CheckResult]] = {}
    for result in report.results:
        grouped.setdefault(result.gate, []).append(result)
    return tuple(
        Gate(code, title, absent, worst_first(tuple(grouped.get(code, ()))))
        for code, title, absent in GATE_TITLES
    )


def decisive(report: Report) -> tuple[CheckResult, ...]:
    by_name = {result.name: result for result in report.results}
    return tuple(by_name[name] for name in DECISIVE if name in by_name)
