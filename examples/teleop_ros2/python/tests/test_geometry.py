# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for ROS pose geometry helpers."""

import numpy as np
import pytest
from scipy.spatial.transform import Rotation

from geometry import (
    apply_manus_controller_to_hand_pose,
    apply_transform_to_pose,
    to_pose,
)


def _orientation(pose) -> np.ndarray:
    return np.array(
        [
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        ]
    )


def _position(pose) -> np.ndarray:
    return np.array([pose.position.x, pose.position.y, pose.position.z])


def test_apply_transform_rotates_translates_and_changes_orientation_basis() -> None:
    pose = to_pose(
        [1.0, 0.0, 0.0],
        Rotation.from_euler("x", 30.0, degrees=True).as_quat(),
    )
    basis_rotation = Rotation.from_euler("z", 90.0, degrees=True)

    transformed = apply_transform_to_pose(
        pose,
        rotation=basis_rotation,
        translation=[1.0, 2.0, 3.0],
    )

    np.testing.assert_allclose(_position(transformed), [1.0, 3.0, 3.0], atol=1e-7)
    expected_orientation = (
        basis_rotation * Rotation.from_quat(_orientation(pose)) * basis_rotation.inv()
    )
    np.testing.assert_allclose(
        Rotation.from_quat(_orientation(transformed)).as_matrix(),
        expected_orientation.as_matrix(),
        atol=1e-7,
    )


def test_apply_transform_returns_a_new_pose_without_mutating_input() -> None:
    pose = to_pose([1.0, 2.0, 3.0], [0.0, 0.0, 0.0, 1.0])

    transformed = apply_transform_to_pose(pose, translation=[4.0, 5.0, 6.0])

    assert transformed is not pose
    np.testing.assert_allclose(_position(pose), [1.0, 2.0, 3.0])
    np.testing.assert_allclose(_position(transformed), [5.0, 7.0, 9.0])


def test_manus_calibration_is_side_specific_and_finite() -> None:
    controller_pose = to_pose([0.1, 0.2, 0.3], [0.0, 0.0, 0.0, 1.0])

    left_hand = apply_manus_controller_to_hand_pose(controller_pose, "left")
    right_hand = apply_manus_controller_to_hand_pose(controller_pose, "right")

    assert np.isfinite(_position(left_hand)).all()
    assert np.isfinite(_orientation(left_hand)).all()
    assert np.isfinite(_position(right_hand)).all()
    assert np.isfinite(_orientation(right_hand)).all()
    assert not np.allclose(_orientation(left_hand), _orientation(right_hand))


def test_manus_calibration_rejects_unknown_side() -> None:
    with pytest.raises(ValueError, match="side must be 'left' or 'right'"):
        apply_manus_controller_to_hand_pose(to_pose([0.0, 0.0, 0.0]), "center")
