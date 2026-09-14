# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit layer: accumulators fed frames built in memory, no MCAP and no fixture set."""

from __future__ import annotations

import math

import pytest
import synth

from fullbody_acceptance.checks import (
    CHECKS,
    Attribution,
    Severity,
    Status,
    build,
    build_all,
)
from fullbody_acceptance.checks.coverage import PayloadPresenceRate
from fullbody_acceptance.checks.quaternion import UnitNormOnValidJoints
from fullbody_acceptance.checks.timestamps import (
    AvailableNotBeforeSample,
    DeviceClockDistinct,
    Monotonic,
)
from fullbody_acceptance.checks.values import Finite, ZeroPoseOnValidJoint
from fullbody_acceptance.report import Verdict, aggregate, run


def drive(check, frame_list):
    for item in frame_list:
        check.update(item)
    return check.result()


def status_of(check_cls, frame_list) -> Status:
    return drive(check_cls(), frame_list).status


# --- the contract itself -----------------------------------------------------------


def test_check_names_are_unique():
    names = [cls.name for cls in CHECKS]
    assert len(names) == len(set(names))


def test_result_reports_insufficient_data_before_any_frame():
    for check in build_all():
        assert check.result().status is Status.INSUFFICIENT_DATA


def test_monotonic_needs_two_frames_to_conclude():
    assert status_of(Monotonic, synth.frames(1)) is Status.INSUFFICIENT_DATA
    assert status_of(Monotonic, synth.frames(2)) is Status.PASS


def test_build_rejects_an_unknown_name():
    with pytest.raises(KeyError):
        build(["values.does_not_exist"])


# --- values ------------------------------------------------------------------------


def test_finite_passes_a_clean_recording():
    assert status_of(Finite, synth.frames(10)) is Status.PASS


def test_finite_catches_nan_and_inf_on_a_valid_joint():
    base = synth.frame(0)
    spoiled = [
        synth.with_joint(base, 3, synth.joint(position=(float("nan"), 1.0, 0.0))),
        synth.with_joint(base, 7, synth.joint(position=(float("inf"), 1.0, 0.0))),
    ]
    outcome = drive(Finite(), spoiled)
    assert outcome.status is Status.FAIL
    assert outcome.measurements["nan_components"] == 1
    assert outcome.measurements["inf_components"] == 1
    assert outcome.measurements["joints"] == [3, 7]


def test_zero_position_fails_only_when_the_joint_claims_to_be_valid():
    base = synth.frame(0)
    zeroed = synth.joint(position=(0.0, 0.0, 0.0), orientation=synth.IDENTITY)
    valid_zero = [synth.with_joint(base, i, zeroed) for i in range(6)]
    assert status_of(ZeroPoseOnValidJoint, valid_zero) is Status.FAIL

    invalid_zero = [
        synth.with_joint(
            base,
            i,
            synth.joint(
                position=(0.0, 0.0, 0.0),
                orientation=(0.0, 0.0, 0.0, 0.0),
                is_valid=False,
            ),
        )
        for i in range(6)
    ]
    assert status_of(ZeroPoseOnValidJoint, invalid_zero) is Status.PASS


# --- quaternion --------------------------------------------------------------------


def test_unit_norm_accepts_a_rotated_but_normalised_orientation():
    rotated = synth.unit_quaternion(math.radians(37), (0.0, 1.0, 0.0))
    frame_list = [
        synth.with_joint(synth.frame(i), 5, synth.joint(orientation=rotated))
        for i in range(4)
    ]
    assert status_of(UnitNormOnValidJoints, frame_list) is Status.PASS


def test_unit_norm_catches_a_scaled_orientation():
    scaled = (0.0, 0.0, 0.0, 1.8)
    frame_list = [synth.with_joint(synth.frame(0), 2, synth.joint(orientation=scaled))]
    outcome = drive(UnitNormOnValidJoints(), frame_list)
    assert outcome.status is Status.FAIL
    assert outcome.measurements["worst_norm"] == pytest.approx(1.8)


def test_unit_norm_ignores_the_all_zero_quaternion_of_an_invalid_joint():
    """make_invalid_body_joint_pose() emits exactly this, so it must not fail."""
    zero_quat = synth.joint(orientation=(0.0, 0.0, 0.0, 0.0), is_valid=False)
    frame_list = [synth.with_joint(synth.frame(i), 9, zero_quat) for i in range(4)]
    assert status_of(UnitNormOnValidJoints, frame_list) is Status.PASS


# --- timestamps --------------------------------------------------------------------


def test_monotonic_catches_a_backward_step():
    frame_list = synth.frames(6)
    frame_list[4] = synth.frame(4, sample_ns=frame_list[3].sample_time_ns - 40_000_000)
    outcome = drive(Monotonic(), frame_list)
    assert outcome.status is Status.FAIL
    assert outcome.measurements["sample_regressions"] == 1
    assert outcome.measurements["worst_step_ms"] == pytest.approx(40.0)


def test_available_equal_to_sample_is_accepted():
    """The Pico tracker passes one monotonic reading as both, so zero latency is normal."""
    sample = synth.CLOCK_BASE_NS
    frame_list = [
        synth.frame(
            i,
            sample_ns=sample + i * synth.PERIOD_NS,
            available_ns=sample + i * synth.PERIOD_NS,
        )
        for i in range(5)
    ]
    assert status_of(AvailableNotBeforeSample, frame_list) is Status.PASS


def test_available_before_sample_fails():
    frame_list = [
        synth.frame(
            i,
            sample_ns=synth.CLOCK_BASE_NS + i * synth.PERIOD_NS,
            available_ns=synth.CLOCK_BASE_NS + i * synth.PERIOD_NS - 5_000_000,
        )
        for i in range(5)
    ]
    assert status_of(AvailableNotBeforeSample, frame_list) is Status.FAIL


def test_device_clock_check_is_advisory_and_never_blocks():
    assert DeviceClockDistinct.severity is Severity.ADVISORY
    frame_list = [
        synth.frame(i, device_ns=synth.CLOCK_BASE_NS + i * synth.PERIOD_NS)
        for i in range(5)
    ]
    outcome = drive(DeviceClockDistinct(), frame_list)
    assert outcome.status is Status.FAIL
    assert outcome.measurements["rate"] == pytest.approx(1.0)

    results = run(synth.StubSource(frame_list)).results
    advisory = next(r for r in results if r.name == DeviceClockDistinct.name)
    assert not advisory.counts_toward_verdict


# --- coverage ----------------------------------------------------------------------


def test_payload_presence_rate():
    present = synth.frames(10)
    assert status_of(PayloadPresenceRate, present) is Status.PASS

    mostly_empty = [synth.frame(i, has_payload=i < 3) for i in range(10)]
    outcome = drive(PayloadPresenceRate(), mostly_empty)
    assert outcome.status is Status.FAIL
    assert outcome.measurements["rate"] == pytest.approx(0.3)


# --- aggregation -------------------------------------------------------------------


def test_a_clean_run_passes_end_to_end():
    report = run(synth.StubSource(synth.frames(30)))
    assert report.verdict is Verdict.PASS
    assert report.failures == ()
    assert report.advisories == ()


def test_advisory_failure_does_not_change_the_verdict():
    frame_list = [
        synth.frame(i, device_ns=synth.CLOCK_BASE_NS + i * synth.PERIOD_NS)
        for i in range(30)
    ]
    report = run(synth.StubSource(frame_list))
    assert report.verdict is Verdict.PASS
    assert [r.name for r in report.advisories] == ["timestamps.device_clock_distinct"]


def test_performance_attribution_yields_retake_not_fail():
    from fullbody_acceptance.report import CheckResult

    def result(name, status, attribution):
        return CheckResult(
            name=name,
            gate="G4",
            severity=Severity.SOFT,
            attribution=attribution,
            summary="",
            status=status,
            detail="",
            measurements={},
        )

    assert aggregate([result("a", Status.PASS, Attribution.DEVICE)]) is Verdict.PASS
    assert (
        aggregate([result("a", Status.FAIL, Attribution.PERFORMANCE)]) is Verdict.RETAKE
    )
    assert (
        aggregate(
            [
                result("a", Status.FAIL, Attribution.PERFORMANCE),
                result("b", Status.FAIL, Attribution.DEVICE),
            ]
        )
        is Verdict.FAIL
    )
    assert (
        aggregate([result("a", Status.INSUFFICIENT_DATA, Attribution.DEVICE)])
        is Verdict.INSUFFICIENT_DATA
    )
