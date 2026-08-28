# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""FrameInfo adapters that guard against silent-corruption bugs.

Duck-typed stubs throughout -- no GPU, no headset, no runtime.
"""

import numpy as np
import pytest

from isaacteleop.viz.robot import frame_info


class _Pose:
    def __init__(self, position, orientation):
        self.position = position
        self.orientation = orientation


class _Fov:
    angle_left = -0.7
    angle_right = 0.7
    angle_up = 0.7
    angle_down = -0.7


class _View:
    def __init__(self, pose, fov=None):
        self.pose = pose
        self.fov = fov or _Fov()


class _Info:
    def __init__(self, views=()):
        self.views = list(views)


def _identity_view():
    return _View(_Pose((1.0, 2.0, 3.0), (1.0, 0.0, 0.0, 0.0)))


def test_head_pose_reorders_the_quaternion():
    """viz reports (w,x,y,z); everything downstream of this takes (x,y,z,w)."""
    view = _View(_Pose((1.0, 2.0, 3.0), (0.5, 0.5, 0.5, 0.5)))
    pose = frame_info.head_pose(_Info(views=[view]))
    np.testing.assert_allclose(pose, [1.0, 2.0, 3.0, 0.5, 0.5, 0.5, 0.5])


def test_head_pose_is_none_without_views():
    assert frame_info.head_pose(_Info()) is None


@pytest.mark.parametrize(
    "orientation",
    [
        (0.0, 0.0, 0.0, 0.0),  # degenerate: carries no orientation
        (float("nan"), 0.0, 0.0, 0.0),
        # Finite and non-degenerate, and still unusable: everything this pose feeds
        # turns a vector by it, and those raise on a non-unit quaternion.
        (0.5, 0.0, 0.0, 0.0),
        (2.0, 0.0, 0.0, 0.0),
    ],
)
def test_head_pose_refuses_unusable_orientations(orientation):
    view = _View(_Pose((0.0, 0.0, 0.0), orientation))
    assert frame_info.head_pose(_Info(views=[view])) is None


def test_head_pose_refuses_non_finite_position():
    view = _View(_Pose((float("inf"), 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)))
    assert frame_info.head_pose(_Info(views=[view])) is None


def test_flatten_views_keeps_wxyz_and_pairs_each_fov():
    """Stereo: two views flatten to 7 pose floats and 4 fov floats each, in order."""
    poses, fovs = frame_info.flatten_views(_Info(views=[_identity_view()] * 2))
    assert len(poses) == 14
    assert len(fovs) == 8
    # Position first, then (w,x,y,z) -- not the (x,y,z,w) head_pose emits.
    assert poses[:7] == [1.0, 2.0, 3.0, 1.0, 0.0, 0.0, 0.0]
    assert fovs[:4] == [
        _Fov.angle_left,
        _Fov.angle_right,
        _Fov.angle_up,
        _Fov.angle_down,
    ]


def test_flatten_views_is_empty_before_the_first_rendered_frame():
    assert frame_info.flatten_views(_Info()) == ([], [])
