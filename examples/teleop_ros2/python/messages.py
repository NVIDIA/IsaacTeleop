# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ROS message and msgpack payload builders for teleop_ros2_node."""

import time
from typing import Dict, Sequence

import numpy as np
from geometry_msgs.msg import Pose, PoseStamped
from scipy.spatial.transform import Rotation
from sensor_msgs.msg import JointState
from teleop_ros2_interfaces.msg import NamedPoseArray

from isaacteleop.retargeting_engine.interface import OptionalTensorGroup
from isaacteleop.retargeting_engine.tensor_types.indices import (
    ControllerInputIndex,
    FullBodyInputIndex,
    HandInputIndex,
    HandJointIndex,
    HeadPoseIndex,
)

from constants import BODY_JOINT_NAMES, HAND_POSE_JOINT_INDICES, HAND_POSE_NAMES
from geometry import (
    apply_manus_controller_to_hand_pose,
    apply_transform_to_pose,
    to_pose,
)
from tensor_group_helpers import (
    controller_aim_is_valid,
    hand_wrist_is_valid,
    head_is_valid,
    joint_names_from_group_type,
)


def _compose_ee_msg(
    left_pose: Pose | None,
    right_pose: Pose | None,
    now,
    frame_id: str,
) -> NamedPoseArray:
    msg = NamedPoseArray()
    msg.header.stamp = now
    msg.header.frame_id = frame_id
    for side, pose in (("left", left_pose), ("right", right_pose)):
        # Set the pose and validity together so the parallel fields cannot diverge.
        if pose is None:
            pose = to_pose([0.0, 0.0, 0.0])
            pose_is_valid = False
        else:
            pose_is_valid = True
        msg.name.append(side)
        msg.pose.append(pose)
        msg.is_valid.append(pose_is_valid)
    return msg


def _compute_ee_pose_from_controller(
    ctrl: OptionalTensorGroup,
    side: str,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
    controller_uses_hands_source: bool = False,
) -> Pose | None:
    if not controller_aim_is_valid(ctrl):
        return None

    pos = [float(x) for x in ctrl[ControllerInputIndex.AIM_POSITION]]
    ori = [float(x) for x in ctrl[ControllerInputIndex.AIM_ORIENTATION]]
    pose = to_pose(pos, ori)

    if transform_rot is not None or transform_trans is not None:
        pose = apply_transform_to_pose(pose, transform_rot, transform_trans)

    if controller_uses_hands_source:
        pose = apply_manus_controller_to_hand_pose(pose, side)

    return pose


def _compute_ee_pose_from_hand(
    hand: OptionalTensorGroup,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
) -> Pose | None:
    if not hand_wrist_is_valid(hand):
        return None

    positions = np.asarray(hand[HandInputIndex.JOINT_POSITIONS])
    orientations = np.asarray(hand[HandInputIndex.JOINT_ORIENTATIONS])
    pose = to_pose(
        positions[HandJointIndex.WRIST],
        orientations[HandJointIndex.WRIST],
    )
    if transform_rot is not None or transform_trans is not None:
        pose = apply_transform_to_pose(pose, transform_rot, transform_trans)
    return pose


def _to_pose_stamped(pose: Pose, now, frame_id: str) -> PoseStamped:
    msg = PoseStamped()
    msg.header.stamp = now
    msg.header.frame_id = frame_id
    msg.pose = pose
    return msg


def build_controller_payload(
    left_ctrl: OptionalTensorGroup, right_ctrl: OptionalTensorGroup
) -> Dict:
    def _as_list(ctrl, index):
        if ctrl.is_none:
            return [0.0, 0.0, 0.0]
        return [float(x) for x in ctrl[index]]

    def _as_quat(ctrl, index):
        if ctrl.is_none:
            return [0.0, 0.0, 0.0, 1.0]
        return [float(x) for x in ctrl[index]]

    def _as_float(ctrl, index):
        if ctrl.is_none:
            return 0.0
        return float(ctrl[index])

    return {
        "timestamp": time.time_ns(),
        "left_thumbstick": [
            _as_float(left_ctrl, ControllerInputIndex.THUMBSTICK_X),
            _as_float(left_ctrl, ControllerInputIndex.THUMBSTICK_Y),
        ],
        "right_thumbstick": [
            _as_float(right_ctrl, ControllerInputIndex.THUMBSTICK_X),
            _as_float(right_ctrl, ControllerInputIndex.THUMBSTICK_Y),
        ],
        "left_trigger_value": _as_float(left_ctrl, ControllerInputIndex.TRIGGER_VALUE),
        "right_trigger_value": _as_float(
            right_ctrl, ControllerInputIndex.TRIGGER_VALUE
        ),
        "left_squeeze_value": _as_float(left_ctrl, ControllerInputIndex.SQUEEZE_VALUE),
        "right_squeeze_value": _as_float(
            right_ctrl, ControllerInputIndex.SQUEEZE_VALUE
        ),
        "left_aim_position": _as_list(left_ctrl, ControllerInputIndex.AIM_POSITION),
        "right_aim_position": _as_list(right_ctrl, ControllerInputIndex.AIM_POSITION),
        "left_grip_position": _as_list(left_ctrl, ControllerInputIndex.GRIP_POSITION),
        "right_grip_position": _as_list(right_ctrl, ControllerInputIndex.GRIP_POSITION),
        "left_aim_orientation": _as_quat(
            left_ctrl, ControllerInputIndex.AIM_ORIENTATION
        ),
        "right_aim_orientation": _as_quat(
            right_ctrl, ControllerInputIndex.AIM_ORIENTATION
        ),
        "left_grip_orientation": _as_quat(
            left_ctrl, ControllerInputIndex.GRIP_ORIENTATION
        ),
        "right_grip_orientation": _as_quat(
            right_ctrl, ControllerInputIndex.GRIP_ORIENTATION
        ),
        "left_primary_click": _as_float(left_ctrl, ControllerInputIndex.PRIMARY_CLICK),
        "right_primary_click": _as_float(
            right_ctrl, ControllerInputIndex.PRIMARY_CLICK
        ),
        "left_secondary_click": _as_float(
            left_ctrl, ControllerInputIndex.SECONDARY_CLICK
        ),
        "right_secondary_click": _as_float(
            right_ctrl, ControllerInputIndex.SECONDARY_CLICK
        ),
        "left_thumbstick_click": _as_float(
            left_ctrl, ControllerInputIndex.THUMBSTICK_CLICK
        ),
        "right_thumbstick_click": _as_float(
            right_ctrl, ControllerInputIndex.THUMBSTICK_CLICK
        ),
        "left_menu_click": _as_float(left_ctrl, ControllerInputIndex.MENU_CLICK),
        "right_menu_click": _as_float(right_ctrl, ControllerInputIndex.MENU_CLICK),
        "left_is_active": not left_ctrl.is_none,
        "right_is_active": not right_ctrl.is_none,
    }


def build_ee_msg_from_controllers(
    left_ctrl: OptionalTensorGroup,
    right_ctrl: OptionalTensorGroup,
    now,
    frame_id: str,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
    controller_uses_hands_source: bool = False,
) -> NamedPoseArray:
    """Build fixed left/right EE entries from controller aim poses."""
    left_pose = _compute_ee_pose_from_controller(
        left_ctrl,
        "left",
        transform_rot,
        transform_trans,
        controller_uses_hands_source,
    )
    right_pose = _compute_ee_pose_from_controller(
        right_ctrl,
        "right",
        transform_rot,
        transform_trans,
        controller_uses_hands_source,
    )
    return _compose_ee_msg(left_pose, right_pose, now, frame_id)


def build_ee_msg_from_hands(
    left_hand: OptionalTensorGroup,
    right_hand: OptionalTensorGroup,
    now,
    frame_id: str,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
) -> NamedPoseArray:
    """Build fixed left/right EE entries from hand wrist poses."""
    left_pose = _compute_ee_pose_from_hand(
        left_hand,
        transform_rot,
        transform_trans,
    )
    right_pose = _compute_ee_pose_from_hand(
        right_hand,
        transform_rot,
        transform_trans,
    )
    return _compose_ee_msg(left_pose, right_pose, now, frame_id)


def build_finger_joints_msg(
    left_joints: OptionalTensorGroup,
    right_joints: OptionalTensorGroup,
    now,
    frame_id: str,
) -> JointState | None:
    if left_joints.is_none and right_joints.is_none:
        return None

    finger_joints_msg = JointState()
    finger_joints_msg.header.stamp = now
    finger_joints_msg.header.frame_id = frame_id
    left_arr = (
        np.asarray(list(left_joints), dtype=np.float32)
        if not left_joints.is_none
        else np.array([], dtype=np.float32)
    )
    right_arr = (
        np.asarray(list(right_joints), dtype=np.float32)
        if not right_joints.is_none
        else np.array([], dtype=np.float32)
    )
    finger_joints_msg.name = (
        joint_names_from_group_type(left_joints.group_type)
        if not left_joints.is_none
        else []
    ) + (
        joint_names_from_group_type(right_joints.group_type)
        if not right_joints.is_none
        else []
    )
    finger_joints_msg.position = np.concatenate([left_arr, right_arr]).tolist()
    return finger_joints_msg


def build_full_body_payload(full_body: OptionalTensorGroup) -> Dict:
    positions = np.asarray(full_body[FullBodyInputIndex.JOINT_POSITIONS])
    orientations = np.asarray(full_body[FullBodyInputIndex.JOINT_ORIENTATIONS])
    valid = np.asarray(full_body[FullBodyInputIndex.JOINT_VALID])

    return {
        "timestamp": time.time_ns(),
        "joint_names": BODY_JOINT_NAMES,
        "joint_positions": [[float(v) for v in pos] for pos in positions],
        "joint_orientations": [[float(v) for v in ori] for ori in orientations],
        "joint_valid": [bool(v) for v in valid],
    }


def build_hand_msg(
    left_hand: OptionalTensorGroup,
    right_hand: OptionalTensorGroup,
    now,
    frame_id: str,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
) -> NamedPoseArray:
    """Build fixed left/right hand joint entries with invalid placeholders."""
    msg = NamedPoseArray()
    msg.header.stamp = now
    msg.header.frame_id = frame_id

    for side, hand in (("left", left_hand), ("right", right_hand)):
        if hand.is_none:
            for joint_name in HAND_POSE_NAMES:
                msg.name.append(f"{side}_{joint_name}")
                msg.pose.append(to_pose([0.0, 0.0, 0.0]))
                msg.is_valid.append(False)
            continue
        positions = np.asarray(hand[HandInputIndex.JOINT_POSITIONS])
        orientations = np.asarray(hand[HandInputIndex.JOINT_ORIENTATIONS])
        joint_valid = np.asarray(hand[HandInputIndex.JOINT_VALID])
        for joint_idx, joint_name in zip(HAND_POSE_JOINT_INDICES, HAND_POSE_NAMES):
            joint_is_valid = bool(joint_valid[joint_idx])
            if joint_is_valid:
                pose = to_pose(positions[joint_idx], orientations[joint_idx])
                if transform_rot is not None or transform_trans is not None:
                    pose = apply_transform_to_pose(pose, transform_rot, transform_trans)
            else:
                pose = to_pose([0.0, 0.0, 0.0])
            msg.name.append(f"{side}_{joint_name}")
            msg.pose.append(pose)
            msg.is_valid.append(joint_is_valid)
    return msg


def build_head_msg(
    head: OptionalTensorGroup,
    now,
    frame_id: str,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
) -> PoseStamped | None:
    """Build a PoseStamped for the head pose, or None when head is invalid."""
    if not head_is_valid(head):
        return None

    position = [float(x) for x in head[HeadPoseIndex.POSITION]]
    orientation = [float(x) for x in head[HeadPoseIndex.ORIENTATION]]
    pose = to_pose(position, orientation)
    if transform_rot is not None or transform_trans is not None:
        pose = apply_transform_to_pose(pose, transform_rot, transform_trans)

    return _to_pose_stamped(pose, now, frame_id)
