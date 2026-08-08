# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Clip-space convention tests for the renderer's projection.

The projection is transcribed from viz's own ``fov_to_projection_matrix``
(src/viz/session/cpp/xr_backend.cpp), including its deliberate angleUp -> bottom
swap. These tests pin the four properties that matter, none of which needs a
GPU, a headset or a VizSession.

`p` is COLUMN-major, so ``p[c * 4 + r]`` is ``P[c][r]``.
"""

import math

import pytest

from isaacteleop_examples.mujoco_xr import _mujoco_xr

NEAR = 0.05
FAR = 50.0

# A plausible asymmetric headset fov, in radians.
FOV = [math.radians(-45.0), math.radians(42.0), math.radians(48.0), math.radians(-46.0)]


def _project(p, x, y, z):
    """Column-major mat4 times (x, y, z, 1), returning NDC after the w-divide."""
    v = (x, y, z, 1.0)
    clip = [sum(p[c * 4 + r] * v[c] for c in range(4)) for r in range(4)]
    return [clip[0] / clip[3], clip[1] / clip[3], clip[2] / clip[3]]


def test_x_scale_is_positive():
    p = _mujoco_xr.projection_from_fov(FOV, NEAR, FAR)
    assert p[0] > 0.0, "P[0][0] <= 0 means left/right are swapped"


def test_y_scale_is_negative_the_deliberate_flip():
    """The load-bearing assertion.

    viz maps angleUp to the frustum's BOTTOM, giving 2n/(t-b) < 0. That
    negative IS the Y flip, and it drives triangle winding. A depth-range check
    touches only P[2][2] / P[2][3] / P[3][2] and would not catch it.
    """
    p = _mujoco_xr.projection_from_fov(FOV, NEAR, FAR)
    assert p[5] < 0.0


def test_depth_is_standard_z_not_reverse_z():
    """near -> 0.0, far -> 1.0.

    Two doc comments in viz claim reverse-Z; the code is standard Z. This test
    is what catches anyone who believes the comments -- reverse-Z would make
    P[2][2] positive and swap these two endpoints.
    """
    p = _mujoco_xr.projection_from_fov(FOV, NEAR, FAR)
    assert p[10] < 0.0
    assert p[14] < 0.0
    assert p[11] == pytest.approx(-1.0)

    assert _project(p, 0.0, 0.0, -NEAR)[2] == pytest.approx(0.0, abs=1e-6)
    assert _project(p, 0.0, 0.0, -FAR)[2] == pytest.approx(1.0, abs=1e-6)


def test_depth_is_monotonic_between_the_planes():
    p = _mujoco_xr.projection_from_fov(FOV, NEAR, FAR)
    depths = [_project(p, 0.0, 0.0, -z)[2] for z in (NEAR, 0.5, 5.0, FAR)]
    assert depths == sorted(depths)


def test_symmetric_fov_centres_the_optical_axis():
    half = math.radians(40.0)
    p = _mujoco_xr.projection_from_fov([-half, half, half, -half], NEAR, FAR)
    assert p[8] == pytest.approx(0.0, abs=1e-6)
    assert p[9] == pytest.approx(0.0, abs=1e-6)
    # A point on the near plane at the right edge of a symmetric frustum lands
    # on x_ndc = +1.
    edge = NEAR * math.tan(half)
    assert _project(p, edge, 0.0, -NEAR)[0] == pytest.approx(1.0, abs=1e-5)


def test_a_default_constructed_fov_is_rejected_loudly():
    """A default-constructed viz::Fov is four ZEROS, and must never render.

    Feeding that through gives right - left == 0 -> P[0][0] = +inf and
    P[2][0] = P[2][1] = NaN, i.e. an all-NaN frame with no error anywhere.
    ``FrameInfo.views`` is filled by the runtime, so a degenerate fov is a
    runtime/session bug the app cannot prevent -- only refuse. Throwing here
    turns a silently blank headset into a named failure.
    """
    with pytest.raises(ValueError):
        _mujoco_xr.projection_from_fov([0.0, 0.0, 0.0, 0.0], NEAR, FAR)


def test_near_far_are_validated():
    with pytest.raises(ValueError):
        _mujoco_xr.projection_from_fov(FOV, 0.0, FAR)
    with pytest.raises(ValueError):
        _mujoco_xr.projection_from_fov(FOV, FAR, NEAR)
