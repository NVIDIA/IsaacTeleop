# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Yaw and anchoring math from ``isaacteleop.viz.robot.anchor``."""

import math

import numpy as np
import pytest

from isaacteleop.viz.robot import anchor

# Identity as xyzw: faces XR -Z.
_FACING_MINUS_Z = np.array([0.0, 0.0, 0.0, 1.0])


def _bearing_deg(q_wxyz):
    """The angle about +Y carried by a yaw quaternion, wrapped into (-180, 180].

    A half turn reports +180, not -180, so a sign can be asserted at every bearing.
    """
    deg = math.degrees(2.0 * math.atan2(q_wxyz[2], q_wxyz[0]))
    return 180.0 - (180.0 - deg) % 360.0


def _pitched(deg):
    """A head orientation (xyzw) pitched about +X; positive looks up."""
    half = math.radians(deg) / 2.0
    return np.array([math.sin(half), 0.0, 0.0, math.cos(half)])


@pytest.mark.parametrize(
    ("forward", "expected_deg"),
    [
        ((0.0, 0.0, -1.0), 0.0),  # straight ahead
        # +90 deg about XR +Y carries -Z onto -X, so -X is the POSITIVE bearing.
        ((-1.0, 0.0, 0.0), 90.0),
        ((1.0, 0.0, 0.0), -90.0),
        ((0.0, 0.0, 1.0), 180.0),
    ],
)
def test_yaw_of_direction_bearings(forward, expected_deg):
    q = anchor.yaw_of_direction(np.array(forward), np.array([0.0, 0.0, -1.0]))
    assert math.isclose(_bearing_deg(q), expected_deg, abs_tol=1e-9)


def test_yaw_of_direction_is_yaw_only():
    """Pitch must not leak: a direction tilted in Y keeps its horizontal bearing."""
    flat = anchor.yaw_of_direction(
        np.array([1.0, 0.0, -1.0]), np.array([0.0, 0.0, -1.0])
    )
    tilted = anchor.yaw_of_direction(
        np.array([1.0, 5.0, -1.0]), np.array([0.0, 0.0, -1.0])
    )
    np.testing.assert_allclose(flat, tilted, atol=1e-12)


def test_yaw_of_direction_negates_the_fallback_pointing_up():
    """The raw primitive, with a fallback a real caller would not pass by itself.

    Callers hand it the pose's own up-vector, which is what makes the reading
    continuous through vertical -- see the heading tests below.
    """
    up = anchor.yaw_of_direction(np.array([0.0, 1.0, 0.0]), np.array([0.0, 0.0, -1.0]))
    assert math.isclose(_bearing_deg(up), 180.0, abs_tol=1e-9)

    down = anchor.yaw_of_direction(
        np.array([0.0, -1.0, 0.0]), np.array([0.0, 0.0, -1.0])
    )
    assert math.isclose(_bearing_deg(down), 0.0, abs_tol=1e-9)


def test_yaw_of_reads_minus_z_of_a_head_pose():
    """A head yawed 30 deg reports 30 deg; identity alone would not show that."""
    assert math.isclose(_bearing_deg(anchor.yaw_of(_FACING_MINUS_Z)), 0.0, abs_tol=1e-9)
    half = math.radians(30.0) / 2.0
    yawed = np.array([0.0, math.sin(half), 0.0, math.cos(half)])
    assert math.isclose(_bearing_deg(anchor.yaw_of(yawed)), 30.0, abs_tol=1e-9)


@pytest.mark.parametrize("pitch_deg", [-90.0, -89.0, 0.0, 89.0, 90.0])
def test_yaw_of_holds_heading_up_to_vertical(pitch_deg):
    """Pitching the head must not swing the twin: the up-vector fallback covers it."""
    assert math.isclose(
        _bearing_deg(anchor.yaw_of(_pitched(pitch_deg))), 0.0, abs_tol=1e-9
    )


@pytest.mark.parametrize("pitch_deg", [-91.0, 91.0])
def test_yaw_of_flips_past_vertical(pitch_deg):
    """Pinning a known wart, not endorsing it.

    One degree past vertical the -Z axis has crossed the horizon and the bearing
    reverses. The near-vertical guard is an absolute 1e-6 and does not reach this.
    """
    assert math.isclose(
        _bearing_deg(anchor.yaw_of(_pitched(pitch_deg))), 180.0, abs_tol=1e-9
    )


def test_anchor_from_head_carries_the_offset_onto_the_facing():
    """With the head facing -Z, the offset is applied unrotated and added to position."""
    head = np.array([1.0, 2.0, 3.0, 0.0, 0.0, 0.0, 1.0])
    offset = np.array([0.0, -0.30, -0.60])
    position, q_yaw = anchor.anchor_from_head(head, offset)
    np.testing.assert_allclose(position, [1.0, 1.70, 2.40], atol=1e-12)
    np.testing.assert_allclose(q_yaw, [1.0, 0.0, 0.0, 0.0], atol=1e-12)


def test_anchor_from_head_rotates_the_offset_with_the_head():
    """Turned 90 deg, a 'forward' offset must come out along the new facing."""
    half = math.sqrt(0.5)
    head = np.array([0.0, 0.0, 0.0, 0.0, half, 0.0, half])  # +90 deg about +Y, xyzw
    position, _ = anchor.anchor_from_head(head, np.array([0.0, 0.0, -1.0]))
    np.testing.assert_allclose(position, [-1.0, 0.0, 0.0], atol=1e-9)


def test_yaw_of_axis_refuses_a_non_unit_quaternion():
    """A short quaternion shrinks the bearing silently.

    The rotation lerps toward the identity rather than scaling, so norm 0.9 turns a
    30 deg yaw into 24.4 deg with nothing to notice it by.
    """
    half = math.radians(30.0) / 2.0
    q = np.array([0.0, math.sin(half), 0.0, math.cos(half)])
    forward = np.array([0.0, 0.0, -1.0])
    assert math.isclose(
        _bearing_deg(anchor.yaw_of_axis(q, forward)), 30.0, abs_tol=1e-9
    )
    with pytest.raises(ValueError, match="unit quaternion"):
        anchor.yaw_of_axis(0.9 * q, forward)


@pytest.mark.parametrize(
    ("q", "expected"),
    [
        ((0.0, 0.0, 0.0, 1.0), True),
        ((0.0, 0.0, 0.0, 1.0 + 5e-4), True),  # inside the drift tolerance
        ((0.0, 0.0, 0.0, 1.0 - 5e-4), True),
        ((0.0, 0.0, 0.0, 0.5), False),  # finite, non-degenerate, and still unusable
        ((0.0, 0.0, 0.0, 0.0), False),
        ((0.0, 0.0, 0.0, float("nan")), False),
        ((0.0, 0.0, 0.0, float("inf")), False),
    ],
)
def test_is_unit(q, expected):
    assert anchor.is_unit(np.array(q)) is expected


def test_is_unit_gates_exactly_what_yaw_of_axis_refuses():
    """One predicate for callers, so a norm-0.5 quaternion cannot reach the raise.

    ``yaw_of_axis`` raises on the frame loop, which ends a session; a caller reading a
    quaternion off a device must be able to ask first, and get the same answer.
    """
    forward = np.array([0.0, 0.0, -1.0])
    for scale in (0.0, 0.5, 0.9, 1.0 - 5e-4, 1.0, 1.0 + 5e-4, 1.1, 2.0):
        q = _FACING_MINUS_Z * scale
        if anchor.is_unit(q):
            anchor.yaw_of_axis(q, forward)
        else:
            with pytest.raises(ValueError, match="unit quaternion"):
                anchor.yaw_of_axis(q, forward)
