# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Test the Python synchronization API; C++ tests cover estimator arithmetic."""

import pytest
from isaacteleop.synchronization import (
    ClockCalibration,
    ClockConversionResult,
    DeviceClockEstimator,
    DeviceClockEstimatorStats,
    ClockObservation,
    ClockStatus,
    make_observation,
)

MS = 1_000_000
SECOND = 1_000_000_000


def exchange(host_send_ns, offset_ns, rtt_ns=400, skew=0.0, epoch_ns=0):
    """One symmetric exchange against a device `offset_ns` ahead and running `skew` fast."""
    t1 = host_send_ns
    t4 = t1 + rtt_ns
    midpoint = t1 + rtt_ns // 2
    device = midpoint + offset_ns + round(skew * (midpoint - epoch_ns))
    # The device replies instantly, so t2 == t3.
    return make_observation(t1, device, device, t4)


def feed(estimator, count, period_ns, offset_ns, skew=0.0, start_ns=0):
    host_ns = start_ns
    for _ in range(count):
        estimator.update(exchange(host_ns, offset_ns, skew=skew, epoch_ns=start_ns))
        host_ns += period_ns
    return host_ns


def test_make_observation_is_bound_and_returns_readable_fields():
    observation = make_observation(1000, 1200 + 5 * MS, 1200 + 5 * MS, 1400)

    assert isinstance(observation, ClockObservation)
    # Check that fields cross the binding boundary.
    assert isinstance(observation.offset_ns, int)
    assert isinstance(observation.rtt_ns, int)
    assert isinstance(observation.device_ns, int)


def test_observation_is_constructible_and_writable():
    observation = ClockObservation()
    assert observation.device_ns == 0

    observation.device_ns = 7
    observation.offset_ns = -3
    observation.rtt_ns = 11
    assert (observation.device_ns, observation.offset_ns, observation.rtt_ns) == (
        7,
        -3,
        11,
    )


def test_calibration_cannot_be_constructed_from_python():
    # Calibrations must come from the estimator.
    with pytest.raises(TypeError):
        ClockCalibration()


def test_calibration_fields_are_read_only():
    estimator = DeviceClockEstimator(DeviceClockEstimator.Mode.Latest)
    estimator.update(exchange(0, 5 * MS))
    calibration = estimator.calibration()

    assert calibration.valid
    with pytest.raises(AttributeError):
        calibration.a_ns = 0.0


def test_estimator_defaults_survive_the_boundary():
    # The default 30 s minimum span pins skew during this 10 s run.
    estimator = DeviceClockEstimator()
    feed(estimator, count=20, period_ns=500 * MS, offset_ns=3 * MS, skew=11.9e-6)

    assert estimator.calibration().valid
    assert estimator.calibration().b == 0.0


def test_mode_enum_round_trips():
    assert DeviceClockEstimator.Mode.Latest != DeviceClockEstimator.Mode.Linear
    estimator = DeviceClockEstimator(
        mode=DeviceClockEstimator.Mode.Latest, window_s=10.0, min_span_s=1.0
    )
    assert estimator.update(exchange(0, 5 * MS))
    assert estimator.calibration().a_ns == pytest.approx(5 * MS)


def test_update_reports_rejection():
    estimator = DeviceClockEstimator()
    host_ns = feed(
        estimator, count=40, period_ns=SECOND, offset_ns=3 * MS, skew=11.9e-6
    )

    # Ten times the usual round trip, so it is rejected rather than fitted.
    assert estimator.update(exchange(host_ns, 3 * MS, rtt_ns=4000)) is False
    assert estimator.stats().rejected == 1


def test_stats_exposes_every_diagnostic():
    estimator = DeviceClockEstimator()
    feed(estimator, count=60, period_ns=SECOND, offset_ns=3 * MS, skew=11.9e-6)
    stats = estimator.stats()

    assert isinstance(stats, DeviceClockEstimatorStats)
    assert stats.skew_ppm == pytest.approx(11.9, abs=0.5)
    assert stats.n > 0
    assert stats.span_s > 0.0
    assert stats.rtt_ns > 0.0
    assert stats.resid_ns >= 0.0
    assert stats.rejected == 0
    assert stats.resets == 0


def test_checked_conversion_result_and_status_round_trip():
    estimator = DeviceClockEstimator(
        mode=DeviceClockEstimator.Mode.Latest,
        window_s=10.0,
        min_span_s=1.0,
        max_extrapolation_windows=2.0,
    )

    uncalibrated = estimator.to_local_common_ns(123)
    assert isinstance(uncalibrated, ClockConversionResult)
    assert uncalibrated.status == ClockStatus.Uncalibrated
    assert uncalibrated.local_common_ns == 0

    observation = exchange(0, 5 * MS)
    assert estimator.update(observation)
    synchronized = estimator.to_local_common_ns(observation.device_ns)
    assert synchronized.status == ClockStatus.Synchronized
    assert isinstance(synchronized.local_common_ns, int)

    stale = estimator.to_local_common_ns(observation.device_ns + 20 * SECOND + 1)
    assert stale.status == ClockStatus.Stale
    assert stale.local_common_ns == 0


def test_extrapolation_limit_must_exceed_one_window():
    with pytest.raises(ValueError, match="greater than one"):
        DeviceClockEstimator(max_extrapolation_windows=1.0)
