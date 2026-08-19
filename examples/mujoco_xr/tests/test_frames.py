# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""The XR -> MuJoCo crossing: the handedness map and the quaternion order.

Both are cheap to get wrong and expensive to debug on hardware.
"""

import math

import numpy as np
import pytest

from isaacteleop_examples.mujoco_xr import _mujoco_xr


def test_extension_and_wheel_share_one_libmujoco():
    import mujoco

    assert _mujoco_xr.mujoco_version() == mujoco.mj_versionString()


def test_axis_map_is_rep103():
    """XR -Z -> MJ +x, +Y -> +z, +X -> -y, on the rotation alone.

    The workspace translation is subtracted, so re-measuring it cannot fail this.
    """
    t = np.asarray(_mujoco_xr.TRANS_MJ_FROM_XR)

    forward = np.asarray(_mujoco_xr.mj_from_xr_pos([0.0, 0.0, -1.0])) - t
    up = np.asarray(_mujoco_xr.mj_from_xr_pos([0.0, 1.0, 0.0])) - t
    right = np.asarray(_mujoco_xr.mj_from_xr_pos([1.0, 0.0, 0.0])) - t

    np.testing.assert_allclose(forward, [1.0, 0.0, 0.0], atol=1e-12)
    np.testing.assert_allclose(up, [0.0, 0.0, 1.0], atol=1e-12)
    np.testing.assert_allclose(right, [0.0, -1.0, 0.0], atol=1e-12)


@pytest.mark.parametrize("eye_height", [0.0, 1.2, 1.6])
def test_point_one_metre_in_front_at_eye_height(eye_height):
    """frames.hpp's definition, executable: a point 1 m in front of the operator
    at eye height h lands at MuJoCo (+1, 0, h), before the workspace translation.
    """
    t = np.asarray(_mujoco_xr.TRANS_MJ_FROM_XR)
    p_mj = np.asarray(_mujoco_xr.mj_from_xr_pos([0.0, eye_height, -1.0])) - t
    np.testing.assert_allclose(p_mj, [1.0, 0.0, eye_height], atol=1e-12)


def test_translation_has_both_terms():
    """Neither term may be silently zeroed: x is operator standoff and z the
    floor datum, and they are independent."""
    t = _mujoco_xr.TRANS_MJ_FROM_XR
    assert t[0] != 0.0, "operator standoff was zeroed"
    assert t[2] != 0.0, "floor datum was zeroed"
    assert t[1] == 0.0


def test_identity_orientation_maps_to_the_convention_quaternion():
    q_xyzw_identity = [0.0, 0.0, 0.0, 1.0]
    q_wxyz = _mujoco_xr.mj_from_xr_quat(q_xyzw_identity)
    np.testing.assert_allclose(q_wxyz, _mujoco_xr.QUAT_MJ_FROM_XR, atol=1e-12)


def test_quaternion_input_order_is_xyzw_not_wxyz():
    """A 90-degree roll about XR +Z, spelled xyzw.

    NINETY degrees, not 180: a 180-degree roll is (0, 0, 1, 0), which read as
    wxyz is a roll about XR +Y, and BOTH send local +x to MuJoCo +y -- a probe
    that passes whichever way the binding reads its input. The second half pins
    that this probe does discriminate.
    """
    import mujoco

    s = math.sin(math.radians(45.0))
    q_xyzw = [0.0, 0.0, s, s]  # (x, y, z, w) = 90 deg about z_xr
    q_wxyz = np.asarray(_mujoco_xr.mj_from_xr_quat(q_xyzw))

    local_x = np.zeros(3)
    mujoco.mju_rotVecQuat(local_x, np.array([1.0, 0.0, 0.0]), q_wxyz)
    np.testing.assert_allclose(local_x, [0.0, 0.0, 1.0], atol=1e-12)

    # The same four numbers misread as wxyz are a 180-degree rotation about
    # (0, s, s), which lands on MuJoCo +y instead. So the assertion above is
    # genuinely sensitive to the component order.
    q_misread = np.asarray(
        _mujoco_xr.mj_from_xr_quat([q_xyzw[1], q_xyzw[2], q_xyzw[3], q_xyzw[0]])
    )
    misread_x = np.zeros(3)
    mujoco.mju_rotVecQuat(misread_x, np.array([1.0, 0.0, 0.0]), q_misread)
    np.testing.assert_allclose(misread_x, [0.0, 1.0, 0.0], atol=1e-12)

    assert math.isclose(float(np.linalg.norm(q_wxyz)), 1.0, rel_tol=1e-9)
