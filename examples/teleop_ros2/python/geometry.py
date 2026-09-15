# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Geometry helpers for ROS message construction."""

from typing import Sequence, Union

import numpy as np
from geometry_msgs.msg import Pose, TransformStamped
from scipy.spatial.transform import Rotation


def apply_manus_controller_to_hand_pose(pose: Pose, side: str) -> Pose:
    """Apply the static MANUS/Pico mount transform in OpenXR space."""
    if side not in ("left", "right"):
        raise ValueError(f"side must be 'left' or 'right', got {side!r}")

    # Hardware-tested new-mount values from isaac-deploy MR !1333.
    mount_rotations = {
        # Historical quaternions are WXYZ; scipy uses XYZW.
        "left": Rotation.from_quat([-0.3375, -0.9049, -0.1575, 0.2059]),
        "right": Rotation.from_quat([0.2458, -0.9423, -0.1851, -0.1316]),
    }
    # Derived controller-local translations for the canonical calibration pose.
    mount_translations = {
        "left": np.array([0.07, -0.045, -0.04], dtype=float),
        "right": np.array([-0.07, -0.045, -0.04], dtype=float),
    }

    controller_position = np.array(
        [pose.position.x, pose.position.y, pose.position.z],
        dtype=float,
    )
    controller_rotation = Rotation.from_quat(
        [
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        ]
    )
    hand_position = controller_position + controller_rotation.apply(
        mount_translations[side]
    )
    hand_rotation = controller_rotation * mount_rotations[side]
    return to_pose(hand_position, hand_rotation.as_quat())


def apply_transform_to_pose(
    pose: Pose,
    rotation: Rotation | None = None,
    translation: Sequence[float] | None = None,
) -> Pose:
    """
    Return a new Pose with world-frame position transform and orientation
    basis change applied.
    """
    p = [pose.position.x, pose.position.y, pose.position.z]
    orientation = Rotation.from_quat(
        [
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        ]
    )

    if rotation is not None:
        p = rotation.apply(p)
        # Conjugation keeps the same physical orientation while expressing it
        # in the rotated basis used for published EE and hand poses.
        orientation = rotation * orientation * rotation.inv()

    q = orientation.as_quat()

    result = Pose()
    if translation is not None:
        result.position.x = float(p[0]) + translation[0]
        result.position.y = float(p[1]) + translation[1]
        result.position.z = float(p[2]) + translation[2]
    else:
        result.position.x = float(p[0])
        result.position.y = float(p[1])
        result.position.z = float(p[2])

    result.orientation.x = float(q[0])
    result.orientation.y = float(q[1])
    result.orientation.z = float(q[2])
    result.orientation.w = float(q[3])
    return result


def make_transform(
    stamp,
    parent_frame: str,
    child_frame: str,
    position: Union[np.ndarray, Sequence[float]],
    orientation: Union[np.ndarray, Sequence[float]],
) -> TransformStamped:
    tf = TransformStamped()
    tf.header.stamp = stamp
    tf.header.frame_id = parent_frame
    tf.child_frame_id = child_frame
    tf.transform.translation.x = float(position[0])
    tf.transform.translation.y = float(position[1])
    tf.transform.translation.z = float(position[2])
    tf.transform.rotation.x = float(orientation[0])
    tf.transform.rotation.y = float(orientation[1])
    tf.transform.rotation.z = float(orientation[2])
    tf.transform.rotation.w = float(orientation[3])
    return tf


def to_pose(position, orientation=None) -> Pose:
    pose = Pose()
    pose.position.x = float(position[0])
    pose.position.y = float(position[1])
    pose.position.z = float(position[2])
    if orientation is None:
        pose.orientation.w = 1.0
    else:
        pose.orientation.x = float(orientation[0])
        pose.orientation.y = float(orientation[1])
        pose.orientation.z = float(orientation[2])
        pose.orientation.w = float(orientation[3])
    return pose
