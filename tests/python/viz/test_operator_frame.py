# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The XR-to-base yaw measurement, which no headless run of the twin exercises."""

from __future__ import annotations

import math

import numpy as np
import pytest
from isaacteleop.viz.robot.operator_frame import OperatorFrame

#: OpenXR (x right, y up, z back) onto REP-103 (x forward, y left, z up).
AXIS_MAP = np.array(
    [
        [0.0, 0.0, -1.0, 0.0],
        [-1.0, 0.0, 0.0, 0.0],
        [0.0, 1.0, 0.0, 0.0],
        [0.0, 0.0, 0.0, 1.0],
    ]
)
FORWARD_BASE = np.array([1.0, 0.0, 0.0])


def bearing_xr(deg: float) -> np.ndarray:
    """A horizontal XR direction at ``deg`` off forward, turning the way a yaw does."""
    t = math.radians(deg)
    return np.array([-math.sin(t), 0.0, -math.cos(t)])


def test_convention_until_measured():
    frame = OperatorFrame(AXIS_MAP)
    assert frame.yaw_rad is None and not frame.measured
    assert np.allclose(frame.transform, AXIS_MAP)


@pytest.mark.parametrize("deg", [0.0, 30.0, 90.0, 179.0, -45.0, -135.0])
def test_recovers_the_yaw(deg):
    """A direction seen at ``deg`` in XR, known to be base +X, means the frames differ by -deg."""
    frame = OperatorFrame(AXIS_MAP)
    frame.update(bearing_xr(deg), FORWARD_BASE, engaged=False)
    assert frame.measured
    # Pushing along XR forward must land at -deg in the base frame.
    landed = frame.transform[:3, :3] @ np.array([0.0, 0.0, -1.0])
    assert math.degrees(math.atan2(landed[1], landed[0])) == pytest.approx(
        -deg, abs=1e-9
    )


def test_translation_is_never_read():
    """The clutch is engage-relative, so a standoff cancels; it must not reach the output."""
    offset = AXIS_MAP.copy()
    offset[:3, 3] = [3.0, -2.0, 0.5]
    frame = OperatorFrame(offset)
    frame.update(bearing_xr(40.0), FORWARD_BASE, engaged=False)
    plain = OperatorFrame(AXIS_MAP)
    plain.update(bearing_xr(40.0), FORWARD_BASE, engaged=False)
    assert np.allclose(frame.transform[:3, :3], plain.transform[:3, :3])


def test_held_while_engaged():
    """The frame the operator engaged under has to be the frame they finish in."""
    frame = OperatorFrame(AXIS_MAP)
    frame.update(bearing_xr(20.0), FORWARD_BASE, engaged=False)
    latched = frame.yaw_rad
    for deg in (60.0, -80.0, 175.0):
        frame.update(bearing_xr(deg), FORWARD_BASE, engaged=True)
        assert frame.yaw_rad == latched


@pytest.mark.parametrize(
    "xr, base",
    [
        (None, FORWARD_BASE),
        (bearing_xr(30.0), None),
        (np.array([0.0, 1.0, 0.0]), FORWARD_BASE),  # straight up: no bearing
        (bearing_xr(30.0), np.array([0.0, 0.0, 1.0])),  # base direction vertical
        (np.array([np.nan, 0.0, -1.0]), FORWARD_BASE),
    ],
)
def test_unusable_observation_holds(xr, base):
    """Absent, vertical or non-finite holds the last yaw rather than latching noise."""
    frame = OperatorFrame(AXIS_MAP)
    frame.update(bearing_xr(25.0), FORWARD_BASE, engaged=False)
    latched = frame.yaw_rad
    frame.update(xr, base, engaged=False)
    assert frame.yaw_rad == latched


def test_rejects_a_bad_axis_map():
    with pytest.raises(ValueError, match="4x4"):
        OperatorFrame(np.eye(3))
