# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Ordering and rendering of the status list."""

from __future__ import annotations

from dataclasses import replace

from full_body_acceptance.checks import Attribution, Severity, Status, build_all
from full_body_acceptance.panel import render, status
from full_body_acceptance.panel.status import GATE_TITLES
from full_body_acceptance.report import CheckResult, Mark, Report, Verdict
from full_body_acceptance.frames import SourceMetadata

METADATA = SourceMetadata(
    schema_name="core.FullBodyPoseRecord",
    schema_encoding="flatbuffer",
    schema_data=b"\x00",
    message_encoding="flatbuffer",
    topic="full_body/full_body",
    profile="teleop",
    channel_found=True,
)


def result(
    name: str,
    *,
    gate: str = "G1",
    status_: Status = Status.PASS,
    severity: Severity = Severity.HARD,
    judged: bool = True,
) -> CheckResult:
    return CheckResult(
        name=name,
        gate=gate,
        severity=severity,
        attribution=Attribution.DEVICE,
        summary="",
        status=status_,
        detail="detail",
        measurements={},
        judged=judged,
    )


def report_of(*results: CheckResult, verdict: Verdict = Verdict.PASS) -> Report:
    return Report(
        source="take.mcap",
        frames=100,
        metadata=METADATA,
        results=results,
        verdict=verdict,
    )


def test_every_state_renders_as_its_own_mark():
    assert result("a").mark is Mark.PASS
    assert result("a", judged=False).mark is Mark.MEAS
    assert result("a", status_=Status.FAIL).mark is Mark.FAIL
    assert (
        result("a", status_=Status.FAIL, severity=Severity.ADVISORY).mark is Mark.NOTE
    )
    assert result("a", status_=Status.INSUFFICIENT_DATA).mark is Mark.UNANSWERED


def test_a_measurement_nobody_judged_does_not_look_like_a_pass():
    """The defect this panel exists to avoid: 70.9 deg of crosstalk printed `pass`."""
    drawn = {mark: render.badge(mark) for mark in Mark}
    assert len(set(drawn.values())) == len(Mark)
    assert render.MARK_COLOURS[Mark.MEAS] != render.MARK_COLOURS[Mark.PASS]
    assert "meas" in drawn[Mark.MEAS]


def test_an_unanswered_check_is_never_drawn_blank():
    """Blank reads as approval."""
    rendered = render.result_rows((result("x", status_=Status.INSUFFICIENT_DATA),))
    assert "n/a" in rendered


def test_a_group_reports_its_worst_result_before_anyone_expands_it():
    report = report_of(
        result("one"),
        result("two", status_=Status.FAIL),
        result("three", judged=False),
    )
    (group,) = status.gates(report)
    assert group.mark is Mark.FAIL
    assert group.tally == "1 FAIL, 1 meas, 1 pass"
    assert [r.mark for r in group.results] == [Mark.FAIL, Mark.MEAS, Mark.PASS]


def test_a_heading_names_what_was_read_and_not_a_gate_number():
    """The numbering is the submitter's narrative; it means nothing to a reviewer."""
    (group,) = status.gates(report_of(result("one")))
    heading = render.gate_heading(group)
    assert heading == "Schema, envelope and signal quality — 1 pass"
    assert group.code not in heading


def test_a_group_with_no_checks_is_not_shown():
    shown = status.gates(report_of(result("one", gate="G4")))
    assert [group.code for group in shown] == ["G4"]


def test_every_gate_the_checks_use_is_displayed():
    """The panel shows groups by name, so an unlisted gate would drop its results."""
    used = {check.gate for check in build_all()}
    assert used <= {code for code, _ in GATE_TITLES}


def test_the_decisive_results_keep_their_own_order():
    report = report_of(
        result("coordinate_frame.up_axis", gate="G2"),
        result("coverage.validity_trend"),
        result("rate.frame_gaps"),
    )
    assert [r.name for r in status.decisive(report)] == [
        "coverage.validity_trend",
        "rate.frame_gaps",
        "coordinate_frame.up_axis",
    ]


def test_a_detail_string_cannot_inject_markup():
    hostile = replace(result("x"), detail="<script>alert(1)</script>")
    assert "<script>" not in render.result_rows((hostile,))


def test_every_verdict_has_a_banner():
    for verdict in Verdict:
        banner = render.verdict_banner(report_of(verdict=verdict))
        assert str(verdict).upper() in banner
