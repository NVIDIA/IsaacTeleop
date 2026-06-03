# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""ROS message and msgpack payload builders for teleop_ros2_node."""

import time
from typing import Dict, Sequence

import numpy as np
from geometry_msgs.msg import PoseArray, PoseStamped
from scipy.spatial.transform import Rotation
from sensor_msgs.msg import JointState

from isaacteleop.retargeting_engine.interface import OptionalTensorGroup
from isaacteleop.retargeting_engine.tensor_types.indices import (
    ControllerInputIndex,
    FullBodyInputIndex,
    HandInputIndex,
    HandJointIndex,
    HeadPoseIndex,
)

from constants import BODY_JOINT_NAMES
from geometry import (
    append_hand_poses,
    apply_manus_controller_to_hand_pose,
    apply_transform_to_pose,
    to_pose,
)


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
) -> PoseArray:
    """Build a PoseArray with left then right controller/hand wrist poses."""
    msg = PoseArray()
    msg.header.stamp = now
    msg.header.frame_id = frame_id

    if controller_aim_is_valid(left_ctrl):
        pos = [float(x) for x in left_ctrl[ControllerInputIndex.AIM_POSITION]]
        ori = [float(x) for x in left_ctrl[ControllerInputIndex.AIM_ORIENTATION]]
        pose = to_pose(pos, ori)

        if transform_rot is not None or transform_trans is not None:
            pose = apply_transform_to_pose(pose, transform_rot, transform_trans)

        if controller_uses_hands_source:
            pose = apply_manus_controller_to_hand_pose(pose, "left")

        msg.poses.append(pose)
    else:
        msg.poses.append(to_pose([0.0, 0.0, 0.0]))

    if controller_aim_is_valid(right_ctrl):
        pos = [float(x) for x in right_ctrl[ControllerInputIndex.AIM_POSITION]]
        ori = [float(x) for x in right_ctrl[ControllerInputIndex.AIM_ORIENTATION]]
        pose = to_pose(pos, ori)

        if transform_rot is not None or transform_trans is not None:
            pose = apply_transform_to_pose(pose, transform_rot, transform_trans)

        if controller_uses_hands_source:
            pose = apply_manus_controller_to_hand_pose(pose, "right")

        msg.poses.append(pose)
    else:
        msg.poses.append(to_pose([0.0, 0.0, 0.0]))

    return msg


def build_ee_msg_from_hands(
    left_hand: OptionalTensorGroup,
    right_hand: OptionalTensorGroup,
    now,
    frame_id: str,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
) -> PoseArray:
    """Build a PoseArray with left then right hand wrist poses (EE proxy)."""
    msg = PoseArray()
    msg.header.stamp = now
    msg.header.frame_id = frame_id

    if hand_joint_is_valid(left_hand, HandJointIndex.WRIST):
        left_positions = np.asarray(left_hand[HandInputIndex.JOINT_POSITIONS])
        left_orientations = np.asarray(left_hand[HandInputIndex.JOINT_ORIENTATIONS])
        pose = to_pose(
            left_positions[HandJointIndex.WRIST],
            left_orientations[HandJointIndex.WRIST],
        )
        if transform_rot is not None or transform_trans is not None:
            pose = apply_transform_to_pose(pose, transform_rot, transform_trans)
        msg.poses.append(pose)
    else:
        msg.poses.append(to_pose([0.0, 0.0, 0.0]))

    if hand_joint_is_valid(right_hand, HandJointIndex.WRIST):
        right_positions = np.asarray(right_hand[HandInputIndex.JOINT_POSITIONS])
        right_orientations = np.asarray(right_hand[HandInputIndex.JOINT_ORIENTATIONS])
        pose = to_pose(
            right_positions[HandJointIndex.WRIST],
            right_orientations[HandJointIndex.WRIST],
        )
        if transform_rot is not None or transform_trans is not None:
            pose = apply_transform_to_pose(pose, transform_rot, transform_trans)
        msg.poses.append(pose)
    else:
        msg.poses.append(to_pose([0.0, 0.0, 0.0]))

    return msg


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


def build_hand_msg_from_hands(
    left_hand: OptionalTensorGroup,
    right_hand: OptionalTensorGroup,
    now,
    frame_id: str,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
) -> PoseArray:
    """Build a PoseArray with finger joint poses, right hand then left hand."""
    msg = PoseArray()
    msg.header.stamp = now
    msg.header.frame_id = frame_id

    if not right_hand.is_none:
        right_positions = np.asarray(right_hand[HandInputIndex.JOINT_POSITIONS])
        right_orientations = np.asarray(right_hand[HandInputIndex.JOINT_ORIENTATIONS])
        right_valid = np.asarray(right_hand[HandInputIndex.JOINT_VALID])
        append_hand_poses(
            msg.poses,
            right_positions,
            right_orientations,
            right_valid,
            transform_rot,
            transform_trans,
        )
    else:
        for _ in range(HandJointIndex.THUMB_METACARPAL, HandJointIndex.LITTLE_TIP + 1):
            msg.poses.append(to_pose([0.0, 0.0, 0.0]))

    if not left_hand.is_none:
        left_positions = np.asarray(left_hand[HandInputIndex.JOINT_POSITIONS])
        left_orientations = np.asarray(left_hand[HandInputIndex.JOINT_ORIENTATIONS])
        left_valid = np.asarray(left_hand[HandInputIndex.JOINT_VALID])
        append_hand_poses(
            msg.poses,
            left_positions,
            left_orientations,
            left_valid,
            transform_rot,
            transform_trans,
        )
    else:
        for _ in range(HandJointIndex.THUMB_METACARPAL, HandJointIndex.LITTLE_TIP + 1):
            msg.poses.append(to_pose([0.0, 0.0, 0.0]))

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

    msg = PoseStamped()
    msg.header.stamp = now
    msg.header.frame_id = frame_id
    msg.pose = pose
    return msg


def controller_aim_is_valid(ctrl: OptionalTensorGroup) -> bool:
    # DeviceIO's AIM_IS_VALID flag is the usability contract for aim poses.
    return not ctrl.is_none and bool(ctrl[ControllerInputIndex.AIM_IS_VALID])


def hand_joint_is_valid(hand: OptionalTensorGroup, joint_idx: HandJointIndex) -> bool:
    if hand.is_none:
        return False
    return bool(hand[HandInputIndex.JOINT_VALID][joint_idx])


def hand_wrist_is_valid(hand: OptionalTensorGroup) -> bool:
    return hand_joint_is_valid(hand, HandJointIndex.WRIST)


def head_is_valid(head: OptionalTensorGroup) -> bool:
    return not head.is_none and bool(head[HeadPoseIndex.IS_VALID])


def joint_names_from_group_type(group_type) -> list[str]:
    return [tensor_type.name for tensor_type in group_type.types]
