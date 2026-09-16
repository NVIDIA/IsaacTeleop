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


@pytest.mark.parametrize(
    ("side", "expected_position", "expected_orientation"),
    (
        (
            "left",
            [-0.07869, -0.01134, 0.00617],
            [-np.sqrt(0.5), -0.5, 0.0, 0.5],
        ),
        (
            "right",
            [0.07869, -0.01134, 0.00617],
            [-np.sqrt(0.5), 0.5, 0.0, 0.5],
        ),
    ),
)
def test_manus_controller_calibration_matches_static_mount(
    side: str,
    expected_position: list[float],
    expected_orientation: list[float],
) -> None:
    controller_pose = to_pose([0.0, 0.0, 0.0], [0.0, 0.0, 0.0, 1.0])

    calibrated_pose = apply_manus_controller_to_hand_pose(controller_pose, side)

    np.testing.assert_allclose(_position(calibrated_pose), expected_position)
    np.testing.assert_allclose(_orientation(calibrated_pose), expected_orientation)


def test_manus_controller_calibration_rotates_controller_local_translation() -> None:
    left_pose = to_pose([-0.2, 1.2, -0.15], [0.0, 0.0, 0.0, 1.0])

    rotated_orientation = Rotation.from_euler("y", 180.0, degrees=True).as_quat()
    left_pose.orientation.x = rotated_orientation[0]
    left_pose.orientation.y = rotated_orientation[1]
    left_pose.orientation.z = rotated_orientation[2]
    left_pose.orientation.w = rotated_orientation[3]
    left_calibrated = apply_manus_controller_to_hand_pose(left_pose, "left")

    np.testing.assert_allclose(
        _position(left_calibrated), [-0.12131, 1.18866, -0.15617]
    )


def test_manus_controller_calibration_rejects_unknown_side() -> None:
    with pytest.raises(ValueError, match="side must be 'left' or 'right'"):
        apply_manus_controller_to_hand_pose(
            to_pose([0.0, 0.0, 0.0]),
            "center",
        )
