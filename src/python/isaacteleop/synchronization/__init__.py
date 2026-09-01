# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Teleop device-clock synchronization.

Maps a device's own free-running clock onto the local common clock, so a sample can carry the
instant it was taken rather than the instant the host got round to reading it.

These are the same estimator the C++ plugins use, so a fit tried here behaves exactly as it will
in the plugin.
"""

from ._synchronization import (
    ClockCalibration,
    ClockConversionResult,
    DeviceClockEstimator,
    DeviceClockEstimatorStats,
    ClockObservation,
    ClockStatus,
    make_observation,
)

__all__ = [
    "ClockCalibration",
    "ClockConversionResult",
    "DeviceClockEstimator",
    "DeviceClockEstimatorStats",
    "ClockObservation",
    "ClockStatus",
    "make_observation",
]
