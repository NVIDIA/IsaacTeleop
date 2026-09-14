# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""G4 is judged by how accurately it measures, not by whether it passes.

The graded fixtures carry the exact injected magnitude in the index, and they exist so
the measurement can be built before anyone knows where the threshold belongs. So these
tests assert two things a threshold cannot give: that the measured value recovers the
injected one, and that the series stays ordered. A check that reported a constant would
satisfy a pass/fail oracle on these fixtures and fail here.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest

from fullbody_acceptance.checks import Status, build
from fullbody_acceptance.labels import StepTimeline
from fullbody_acceptance.mcap_source import McapFrameSource
from fullbody_acceptance.report import run

# Each graded series: the check that measures it, the measurement key, and how to turn
# the index's injected value into that key's units.
SERIES = {
    "cumulative_drift": (
        "posture.cumulative_drift_between_tpose_windows",
        "drift_rad",
        lambda value: value,
    ),
    "contralateral_crosstalk": (
        "posture.contralateral_crosstalk_single_leg_raise",
        "crosstalk_deg",
        lambda value: value,
    ),
    "tpose_arm_droop": ("posture.tpose_arm_droop", "droop_deg", lambda value: value),
    "tpose_left_right_asymmetry": (
        "posture.tpose_left_right_asymmetry",
        "asymmetry_deg",
        lambda value: value,
    ),
}

# The generator writes exact angles and the recovery is analytic, so the tolerance only
# has to absorb float32 storage in the MCAP payload.
TOLERANCE = {"rad": 5e-4, "deg": 0.05}


def graded_fixtures(index: dict) -> list[dict]:
    return [f for f in index["fixtures"] if f.get("category") == "graded"]


def measure(fixture_dir: Path, entry: dict, check_name: str) -> dict:
    path = fixture_dir / entry["filename"]
    timeline = StepTimeline.beside(path)
    checks = build([check_name], timeline)
    report = run(McapFrameSource(path), checks, timeline)
    (result,) = report.results
    assert result.status is not Status.INSUFFICIENT_DATA, result.detail
    return result.measurements


def fixture_id(entry: dict) -> str:
    return Path(entry["filename"]).stem


class TestGradedAccuracy:
    def test_every_graded_fixture_is_covered(self, index: dict):
        """Guards against a series being added upstream with no measurement behind it."""
        quantities = {f["injected"]["quantity"] for f in graded_fixtures(index)}
        assert quantities <= set(SERIES), (
            f"unmeasured graded quantities: {quantities - set(SERIES)}"
        )

    def test_measured_value_recovers_the_injected_one(
        self, fixture_dir: Path, index: dict
    ):
        errors = []
        for entry in graded_fixtures(index):
            injected = entry["injected"]
            check_name, key, convert = SERIES[injected["quantity"]]
            measured = measure(fixture_dir, entry, check_name)[key]
            expected = convert(injected["value"])
            if abs(measured - expected) > TOLERANCE[injected["unit"]]:
                errors.append(
                    f"{fixture_id(entry)}: {key} measured {measured:.5f}, "
                    f"injected {expected:.5f}"
                )
        assert not errors, "\n".join(errors)

    @pytest.mark.parametrize("quantity", sorted(SERIES))
    def test_the_series_stays_ordered(
        self, fixture_dir: Path, index: dict, quantity: str
    ):
        check_name, key, convert = SERIES[quantity]
        ladder = sorted(
            (
                (convert(f["injected"]["value"]), fixture_id(f), f)
                for f in graded_fixtures(index)
                if f["injected"]["quantity"] == quantity
            )
        )
        if len(ladder) < 3:
            pytest.skip(f"{quantity} has {len(ladder)} rungs")

        measured = [
            (name, measure(fixture_dir, entry, check_name)[key])
            for _, name, entry in ladder
        ]
        for (earlier, low), (later, high) in zip(measured, measured[1:]):
            assert high > low, (
                f"{quantity} not monotonic: {earlier}={low}, {later}={high}"
            )

    def test_the_zero_rung_reads_zero(self, fixture_dir: Path, index: dict):
        """A measurement with an offset would still be monotonic and still be wrong."""
        for entry in graded_fixtures(index):
            if entry["injected"]["value"] != 0.0:
                continue
            check_name, key, _ = SERIES[entry["injected"]["quantity"]]
            measured = measure(fixture_dir, entry, check_name)[key]
            unit = entry["injected"]["unit"]
            assert abs(measured) <= TOLERANCE[unit], (
                f"{fixture_id(entry)}: {key}={measured}"
            )


class TestGradedStaysAdvisory:
    def test_a_graded_recording_is_not_failed_on_an_uncalibrated_threshold(
        self, fixture_dir: Path, index: dict
    ):
        """The index marks these "graded", which is neither a pass nor a fail.

        Until real recordings calibrate the thresholds, the honest report is the number,
        so these checks must not drag a recording to a verdict they cannot justify.
        """
        worst = max(
            (f for f in graded_fixtures(index)),
            key=lambda f: abs(f["injected"]["value"]),
        )
        report = run(McapFrameSource(fixture_dir / worst["filename"]))
        assert report.verdict.value == "pass"
        assert not report.failures


class TestG4Faults:
    """Device faults must read as fail and sloppy performances as retake, never swapped."""

    def g4_faults(self, index: dict) -> list[dict]:
        return [
            f
            for f in index["fixtures"]
            if f["batch"] == "g4_posture" and f.get("expected_failing_check")
        ]

    def test_each_fault_fixture_fails_its_named_check(
        self, fixture_dir: Path, index: dict
    ):
        errors = []
        for entry in self.g4_faults(index):
            report = run(McapFrameSource(fixture_dir / entry["filename"]))
            failing = {r.name for r in report.failures}
            wanted = entry["expected_failing_check"]
            if wanted not in failing:
                errors.append(
                    f"{fixture_id(entry)}: wanted {wanted}, got {sorted(failing)}"
                )
            if report.verdict.value != entry["expected_verdict"]:
                errors.append(
                    f"{fixture_id(entry)}: verdict {report.verdict.value}, "
                    f"wanted {entry['expected_verdict']}"
                )
        assert not errors, "\n".join(errors)

    def test_a_mislabelled_session_is_never_blamed_on_the_device(
        self, fixture_dir: Path, index: dict
    ):
        """The window labelled "right arm raise" holds a leg raise in this fixture.

        Measured naively the arm never leaves its side, which reads as a device clipping
        the arm's range. Reporting that would send a vendor after a fault the operator
        caused, so the device measurements must decline instead.
        """
        entry = next(
            f
            for f in index["fixtures"]
            if fixture_id(f) == "g4_perf_steps_out_of_order"
        )
        report = run(McapFrameSource(fixture_dir / entry["filename"]))
        assert report.verdict.value == "retake"
        assert all(r.attribution.value == "performance" for r in report.failures)
        declined = {r.name for r in report.unanswered}
        assert "posture.arm_raise_range_of_motion" in declined

    def test_broken_label_windows_suppress_the_measurements_they_would_corrupt(
        self, fixture_dir: Path, index: dict
    ):
        entry = next(
            f for f in index["fixtures"] if fixture_id(f) == "g4_seg_labels_offset"
        )
        report = run(McapFrameSource(fixture_dir / entry["filename"]))
        assert {r.name for r in report.failures} == {"segmentation.label_alignment"}
        posture = [r for r in report.results if r.name.startswith("posture.")]
        assert posture and all(r.status is Status.INSUFFICIENT_DATA for r in posture)


class TestWithoutLabels:
    def test_a_recording_without_labels_still_passes_the_rest(
        self, fixture_dir: Path, index: dict
    ):
        entry = next(
            f for f in index["fixtures"] if fixture_id(f) == "g4_seg_labels_absent"
        )
        path = fixture_dir / entry["filename"]
        assert StepTimeline.beside(path) is None
        report = run(McapFrameSource(path))
        assert report.verdict.value == "pass"

        # Every windowed check declines except the one whose job is to say so.
        fallback = "segmentation.fallback_without_labels"
        windowed = [r for r in report.results if r.gate == "G4" and r.name != fallback]
        assert windowed and all(r.status is Status.INSUFFICIENT_DATA for r in windowed)

        (reported,) = [r for r in report.results if r.name == fallback]
        assert reported.status is Status.PASS
        assert reported.measurements["labels_present"] is False
        assert any("no motion-step labels" in note for note in report.notes)


class TestLabelTimeline:
    def test_wellformed_labels_report_no_defects(self, fixture_dir: Path):
        timeline = StepTimeline.load(
            fixture_dir / "fixtures/g4/g4_golden_full_script.labels.json"
        )
        assert timeline.defects() == ()
        assert len(timeline.steps) == 11

    def test_overlaps_and_gaps_are_both_named(self, fixture_dir: Path):
        timeline = StepTimeline.load(
            fixture_dir / "fixtures/g4/g4_seg_labels_overlap_and_gaps.labels.json"
        )
        kinds = {defect.kind for defect in timeline.defects()}
        assert {"overlap", "gap"} <= kinds

    def test_a_step_is_found_by_its_own_timestamps(self, fixture_dir: Path):
        timeline = StepTimeline.load(
            fixture_dir / "fixtures/g4/g4_golden_full_script.labels.json"
        )
        step = timeline.one("squat_x2")
        assert step is not None
        assert timeline.step_at(step.start_ns) is step
        assert timeline.step_at(step.end_ns) is not step
        assert timeline.step_at(None) is None


class TestSignedAngles:
    def test_the_axis_projection_keeps_the_sign(self):
        """``2*acos(w)`` would return a magnitude, losing which way a joint turned."""
        from fullbody_acceptance.vectors import signed_angle_about
        from tests import synth

        for degrees in (-80.0, -12.5, 0.0, 7.0, 95.0):
            q = synth.unit_quaternion(math.radians(degrees), (0.0, 0.0, 1.0))
            measured = math.degrees(signed_angle_about(q, (0.0, 0.0, 1.0)))
            assert measured == pytest.approx(degrees, abs=1e-6)

    def test_a_child_rotation_is_read_relative_to_its_parent(self):
        from fullbody_acceptance.vectors import multiply, relative, signed_angle_about
        from tests import synth

        parent = synth.unit_quaternion(math.radians(30.0), (0.0, 1.0, 0.0))
        local = synth.unit_quaternion(math.radians(-40.0), (0.0, 0.0, 1.0))
        child = multiply(parent, local)
        recovered = math.degrees(
            signed_angle_about(relative(parent, child), (0.0, 0.0, 1.0))
        )
        assert recovered == pytest.approx(-40.0, abs=1e-6)
