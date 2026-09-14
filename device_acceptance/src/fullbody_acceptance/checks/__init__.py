# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Check registry.

Names match the ``expected_failing_check`` strings in the fixture index; that index is
the specification for this vocabulary, so nothing here invents a name.
"""

from __future__ import annotations

from .base import Attribution, Check, Outcome, Severity, Status
from .coverage import PayloadPresenceRate
from .quaternion import UnitNormOnValidJoints
from .timestamps import AvailableNotBeforeSample, DeviceClockDistinct, Monotonic
from .values import Finite, ZeroPoseOnValidJoint

CHECKS: tuple[type[Check], ...] = (
    Finite,
    ZeroPoseOnValidJoint,
    UnitNormOnValidJoints,
    Monotonic,
    AvailableNotBeforeSample,
    DeviceClockDistinct,
    PayloadPresenceRate,
)


def build_all() -> list[Check]:
    return [cls() for cls in CHECKS]


def build(names: list[str]) -> list[Check]:
    by_name = {cls.name: cls for cls in CHECKS}
    unknown = [name for name in names if name not in by_name]
    if unknown:
        raise KeyError(f"unknown checks: {unknown}")
    return [by_name[name]() for name in names]


__all__ = [
    "CHECKS",
    "Attribution",
    "Check",
    "Outcome",
    "Severity",
    "Status",
    "build",
    "build_all",
]
