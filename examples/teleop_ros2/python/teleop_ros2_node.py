#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Teleop ROS2 Reference Node.

Publishes teleoperation data over ROS2 topics using isaacteleop TeleopSession.
The `mode` parameter selects the teleoperation scenario and which topics are
published:

  - controller_teleop (default): ee_poses (from controller aim pose), root_twist, root_pose,
                       finger_joints (retargeted TriHand angles), and TF transforms for
                       left/right wrists
  - hand_teleop: ee_poses (from hand tracking wrist), hand (finger joint poses),
                 root_twist, root_pose, and TF transforms for left/right wrists
  - controller_raw: controller_data only
  - full_body: full_body and controller_data

Topic names (remappable via ROS 2 remapping):
  - xr_teleop/hand (PoseArray): [finger_joint_poses...]
  - xr_teleop/ee_poses (PoseArray): [right_ee, left_ee]
  - xr_teleop/root_twist (TwistStamped): root velocity command
  - xr_teleop/root_pose (PoseStamped): root pose command (height only)
  - xr_teleop/controller_data (ByteMultiArray): msgpack-encoded controller data
  - xr_teleop/full_body (ByteMultiArray): msgpack-encoded full body tracking data
  - xr_teleop/finger_joints (JointState): retargeted TriHand finger joint angles (controller_teleop only)

TF frames published in hand_teleop and controller_teleop modes (configurable via parameters):
  - world_frame -> right_wrist_frame
  - world_frame -> left_wrist_frame
"""

import math
import os
import time
from pathlib import Path
from typing import Dict, List, Sequence, Union

import msgpack
import msgpack_numpy as mnp
import numpy as np
import rclpy
from scipy.spatial.transform import Rotation
from geometry_msgs.msg import (
    Pose,
    PoseArray,
    PoseStamped,
    TransformStamped,
    TwistStamped,
)
from rcl_interfaces.msg import ParameterDescriptor
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import ByteMultiArray
from tf2_ros import TransformBroadcaster

from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
    FullBodySource,
    HandsSource,
)
from isaacteleop.retargeting_engine.interface import OptionalTensorGroup, OutputCombiner
from isaacteleop.retargeters import (
    LocomotionRootCmdRetargeter,
    LocomotionRootCmdRetargeterConfig,
    TriHandMotionControllerRetargeter,
    TriHandMotionControllerConfig,
)
from isaacteleop.retargeting_engine.tensor_types.indices import (
    BodyJointPicoIndex,
    ControllerInputIndex,
    FullBodyInputIndex,
    HandInputIndex,
    HandJointIndex,
)
from isaacteleop.teleop_session_manager import (
    PluginConfig,
    TeleopSession,
    TeleopSessionConfig,
)

_BODY_JOINT_NAMES = [e.name for e in BodyJointPicoIndex]
_TELEOP_MODES = ("controller_teleop", "hand_teleop", "controller_raw", "full_body")

_TRIHAND_JOINT_NAMES = [
    "thumb_rotation",
    "thumb_proximal",
    "thumb_distal",
    "index_proximal",
    "index_distal",
    "middle_proximal",
    "middle_distal",
]
_FINGER_JOINT_COUNT = len(_TRIHAND_JOINT_NAMES)
_LEFT_FINGER_JOINT_NAMES = [f"left_{n}" for n in _TRIHAND_JOINT_NAMES]
_RIGHT_FINGER_JOINT_NAMES = [f"right_{n}" for n in _TRIHAND_JOINT_NAMES]


# Helper functions


def _append_hand_poses(
    poses: List[Pose],
    joint_positions: np.ndarray,
    joint_orientations: np.ndarray,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
) -> None:
    for joint_idx in range(
        HandJointIndex.THUMB_METACARPAL, HandJointIndex.LITTLE_TIP + 1
    ):
        pose = _to_pose(joint_positions[joint_idx], joint_orientations[joint_idx])
        if transform_rot is not None or transform_trans is not None:
            pose = _apply_transform_to_pose(pose, transform_rot, transform_trans)
        poses.append(pose)


def _apply_transform_to_pose(
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


def _find_plugins_dirs(start: Path) -> List[Path]:
    candidates: List[Path] = []
    for parent in [start, *start.parents]:
        plugin_dir = parent / "plugins"
        if plugin_dir.is_dir() and plugin_dir not in candidates:
            candidates.append(plugin_dir)
    return candidates


def _joint_names_from_group(group: OptionalTensorGroup) -> List[str]:
    return [tensor_type.name for tensor_type in group.group_type.types]


def _make_transform(
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


def _resolve_finger_joint_names(
    parameter_name: str,
    names: Sequence[str],
) -> List[str]:
    if len(names) != _FINGER_JOINT_COUNT:
        raise ValueError(
            f"Parameter '{parameter_name}' must contain exactly "
            f"{_FINGER_JOINT_COUNT} entries in TriHand order, got {len(names)}"
        )

    resolved_names = list(names)
    for index, joint_name in enumerate(resolved_names, start=1):
        if not joint_name.strip():
            raise ValueError(
                f"Parameter '{parameter_name}' entry {index} must be a non-empty string"
            )

    return resolved_names


def _to_pose(position, orientation=None) -> Pose:
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


# Message builders


def _build_ee_msg_from_controllers(
    left_ctrl: OptionalTensorGroup,
    right_ctrl: OptionalTensorGroup,
    now,
    frame_id: str,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
) -> PoseArray:
    """Build a PoseArray with right then left controller aim poses (wrist proxy)."""
    msg = PoseArray()
    msg.header.stamp = now
    msg.header.frame_id = frame_id
    if not right_ctrl.is_none:
        pos = [float(x) for x in right_ctrl[ControllerInputIndex.AIM_POSITION]]
        ori = [float(x) for x in right_ctrl[ControllerInputIndex.AIM_ORIENTATION]]
        pose = _to_pose(pos, ori)
        if transform_rot is not None or transform_trans is not None:
            pose = _apply_transform_to_pose(pose, transform_rot, transform_trans)
        msg.poses.append(pose)
    else:
        msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    if not left_ctrl.is_none:
        pos = [float(x) for x in left_ctrl[ControllerInputIndex.AIM_POSITION]]
        ori = [float(x) for x in left_ctrl[ControllerInputIndex.AIM_ORIENTATION]]
        pose = _to_pose(pos, ori)
        if transform_rot is not None or transform_trans is not None:
            pose = _apply_transform_to_pose(pose, transform_rot, transform_trans)
        msg.poses.append(pose)
    else:
        msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    return msg


def _build_ee_msg_from_hands(
    left_hand: OptionalTensorGroup,
    right_hand: OptionalTensorGroup,
    now,
    frame_id: str,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
) -> PoseArray:
    """Build a PoseArray with right then left hand wrist poses (EE proxy)."""
    msg = PoseArray()
    msg.header.stamp = now
    msg.header.frame_id = frame_id

    if not right_hand.is_none:
        right_positions = np.asarray(right_hand[HandInputIndex.JOINT_POSITIONS])
        right_orientations = np.asarray(right_hand[HandInputIndex.JOINT_ORIENTATIONS])
        pose = _to_pose(
            right_positions[HandJointIndex.WRIST],
            right_orientations[HandJointIndex.WRIST],
        )
        if transform_rot is not None or transform_trans is not None:
            pose = _apply_transform_to_pose(pose, transform_rot, transform_trans)
        msg.poses.append(pose)
    else:
        msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    if not left_hand.is_none:
        left_positions = np.asarray(left_hand[HandInputIndex.JOINT_POSITIONS])
        left_orientations = np.asarray(left_hand[HandInputIndex.JOINT_ORIENTATIONS])
        pose = _to_pose(
            left_positions[HandJointIndex.WRIST],
            left_orientations[HandJointIndex.WRIST],
        )
        if transform_rot is not None or transform_trans is not None:
            pose = _apply_transform_to_pose(pose, transform_rot, transform_trans)
        msg.poses.append(pose)
    else:
        msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    return msg


def _build_hand_msg_from_hands(
    left_hand: OptionalTensorGroup,
    right_hand: OptionalTensorGroup,
    now,
    frame_id: str,
    transform_rot: Rotation | None = None,
    transform_trans: Sequence[float] | None = None,
) -> PoseArray:
    """Build a PoseArray with right then left hand finger joints."""
    msg = PoseArray()
    msg.header.stamp = now
    msg.header.frame_id = frame_id

    if not right_hand.is_none:
        right_positions = np.asarray(right_hand[HandInputIndex.JOINT_POSITIONS])
        right_orientations = np.asarray(right_hand[HandInputIndex.JOINT_ORIENTATIONS])
        _append_hand_poses(
            msg.poses,
            right_positions,
            right_orientations,
            transform_rot,
            transform_trans,
        )
    else:
        for _ in range(HandJointIndex.THUMB_METACARPAL, HandJointIndex.LITTLE_TIP + 1):
            msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    if not left_hand.is_none:
        left_positions = np.asarray(left_hand[HandInputIndex.JOINT_POSITIONS])
        left_orientations = np.asarray(left_hand[HandInputIndex.JOINT_ORIENTATIONS])
        _append_hand_poses(
            msg.poses, left_positions, left_orientations, transform_rot, transform_trans
        )
    else:
        for _ in range(HandJointIndex.THUMB_METACARPAL, HandJointIndex.LITTLE_TIP + 1):
            msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    return msg


def _build_controller_payload(
    left_ctrl: OptionalTensorGroup, right_ctrl: OptionalTensorGroup
) -> Dict:
    def _as_list(ctrl, index):
        if ctrl.is_none:
            return [0.0, 0.0, 0.0]
        return [float(x) for x in ctrl[index]]

    def _as_quat(ctrl, index):
        if ctrl.is_none:
            return [1.0, 0.0, 0.0, 0.0]
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
        "left_is_active": not left_ctrl.is_none,
        "right_is_active": not right_ctrl.is_none,
    }


def _build_full_body_payload(full_body: OptionalTensorGroup) -> Dict:
    positions = np.asarray(full_body[FullBodyInputIndex.JOINT_POSITIONS])
    orientations = np.asarray(full_body[FullBodyInputIndex.JOINT_ORIENTATIONS])
    valid = np.asarray(full_body[FullBodyInputIndex.JOINT_VALID])

    return {
        "timestamp": time.time_ns(),
        "joint_names": _BODY_JOINT_NAMES,
        "joint_positions": [[float(v) for v in pos] for pos in positions],
        "joint_orientations": [[float(v) for v in ori] for ori in orientations],
        "joint_valid": [bool(v) for v in valid],
    }


class TeleopRos2Node(Node):
    """ROS 2 node that publishes teleop data."""

    def __init__(self) -> None:
        super().__init__("teleop_ros2_node")

        self.declare_parameter("mode", "controller_teleop")
        self.declare_parameter("rate_hz", 60.0)
        self.declare_parameter("use_mock_operators", value=False)

        self.declare_parameter(
            "transform_translation",
            [0.0, 0.0, 0.0],
            ParameterDescriptor(
                description=(
                    "Optional translation [x, y, z] applied to published "
                    "hand/EE pose positions after rotating them into the ROS "
                    "world frame."
                )
            ),
        )
        self.declare_parameter(
            "transform_rotation",
            [0.0, 0.0, 0.0, 1.0],
            ParameterDescriptor(
                description=(
                    "Optional rotation [qx, qy, qz, qw] used to rotate "
                    "published hand/EE pose positions into the ROS world "
                    "frame and re-express their orientations in that rotated "
                    "basis."
                )
            ),
        )

        self.declare_parameter(
            "world_frame",
            "world",
            ParameterDescriptor(
                description=(
                    "World frame used as the header frame_id for all published messages "
                    "and as the parent frame for wrist TF transforms. Defaults to 'world'."
                )
            ),
        )
        self.declare_parameter(
            "right_wrist_frame",
            "right_wrist",
            ParameterDescriptor(description="TF child frame name for the right wrist."),
        )
        self.declare_parameter(
            "left_wrist_frame",
            "left_wrist",
            ParameterDescriptor(description="TF child frame name for the left wrist."),
        )

        finger_joint_name_constraints = (
            f"Provide exactly {_FINGER_JOINT_COUNT} joint names matching the "
            f"TriHand order {_TRIHAND_JOINT_NAMES}."
        )
        self.declare_parameter(
            "left_finger_joint_names",
            list(_LEFT_FINGER_JOINT_NAMES),
            ParameterDescriptor(
                description=(
                    "Published joint names for the left hand on "
                    "xr_teleop/finger_joints. Defaults to the prefixed TriHand names."
                ),
                additional_constraints=finger_joint_name_constraints,
            ),
        )
        self.declare_parameter(
            "right_finger_joint_names",
            list(_RIGHT_FINGER_JOINT_NAMES),
            ParameterDescriptor(
                description=(
                    "Published joint names for the right hand on "
                    "xr_teleop/finger_joints. Defaults to the prefixed TriHand names."
                ),
                additional_constraints=finger_joint_name_constraints,
            ),
        )

        rate_hz = self.get_parameter("rate_hz").get_parameter_value().double_value
        if rate_hz <= 0 or not math.isfinite(rate_hz):
            raise ValueError("Parameter 'rate_hz' must be > 0")
        self._sleep_period_s: float = 1.0 / rate_hz
        self._use_mock_operators: bool = (
            self.get_parameter("use_mock_operators").get_parameter_value().bool_value
        )
        mode = self.get_parameter("mode").get_parameter_value().string_value
        if mode not in _TELEOP_MODES:
            raise ValueError(
                f"Parameter 'mode' must be one of {_TELEOP_MODES}, got {mode!r}"
            )
        self.get_logger().info(f"Mode: {mode}")
        self._mode: str = mode

        self._world_frame: str = (
            self.get_parameter("world_frame").get_parameter_value().string_value
        )
        self._right_wrist_frame: str = (
            self.get_parameter("right_wrist_frame").get_parameter_value().string_value
        )
        self._left_wrist_frame: str = (
            self.get_parameter("left_wrist_frame").get_parameter_value().string_value
        )
        if not self._world_frame:
            raise ValueError("Parameter 'world_frame' must not be empty")
        if not self._right_wrist_frame:
            raise ValueError("Parameter 'right_wrist_frame' must not be empty")
        if not self._left_wrist_frame:
            raise ValueError("Parameter 'left_wrist_frame' must not be empty")
        if self._right_wrist_frame == self._left_wrist_frame:
            raise ValueError(
                f"'right_wrist_frame' and 'left_wrist_frame' must be different , got {self._right_wrist_frame!r}"
            )
        if self._right_wrist_frame == self._world_frame:
            raise ValueError(
                f"'right_wrist_frame' must be different from 'world_frame', got {self._right_wrist_frame!r}"
            )
        if self._left_wrist_frame == self._world_frame:
            raise ValueError(
                f"'left_wrist_frame' must be different from 'world_frame', got {self._left_wrist_frame!r}"
            )

        transform_trans_arr = (
            self.get_parameter("transform_translation")
            .get_parameter_value()
            .double_array_value
        )
        self._transform_trans: List[float] | None = None
        if transform_trans_arr:
            if len(transform_trans_arr) != 3:
                raise ValueError(
                    "Parameter 'transform_translation' must have 3 elements if provided"
                )
            if not np.allclose(transform_trans_arr, [0.0, 0.0, 0.0]):
                self._transform_trans = [float(x) for x in transform_trans_arr]

        transform_rot_arr = (
            self.get_parameter("transform_rotation")
            .get_parameter_value()
            .double_array_value
        )
        self._transform_rot: Rotation | None = None
        if transform_rot_arr:
            if len(transform_rot_arr) != 4:
                raise ValueError(
                    "Parameter 'transform_rotation' must have 4 elements if provided"
                )
            if not np.allclose(transform_rot_arr, [0.0, 0.0, 0.0, 1.0]):
                # Validate and normalize the quaternion
                transform_rot_floats = [float(x) for x in transform_rot_arr]
                q_norm = np.linalg.norm(transform_rot_floats)
                if q_norm < 1e-6:
                    raise ValueError(
                        "Parameter 'transform_rotation' must be a valid non-zero quaternion"
                    )
                if not math.isclose(q_norm, 1.0, rel_tol=1e-3):
                    self.get_logger().warn(
                        f"Parameter 'transform_rotation' is not a unit quaternion (norm={q_norm}). Normalizing it."
                    )
                normalized_q = np.array(transform_rot_floats) / q_norm
                self._transform_rot = Rotation.from_quat(normalized_q)

        left_finger_joint_names = _resolve_finger_joint_names(
            "left_finger_joint_names",
            self.get_parameter("left_finger_joint_names").value,
        )
        right_finger_joint_names = _resolve_finger_joint_names(
            "right_finger_joint_names",
            self.get_parameter("right_finger_joint_names").value,
        )

        self._tf_broadcaster = TransformBroadcaster(self)

        self._pub_hand = self.create_publisher(PoseArray, "xr_teleop/hand", 10)
        self._pub_ee_pose = self.create_publisher(PoseArray, "xr_teleop/ee_poses", 10)
        self._pub_root_twist = self.create_publisher(
            TwistStamped, "xr_teleop/root_twist", 10
        )
        self._pub_root_pose = self.create_publisher(
            PoseStamped, "xr_teleop/root_pose", 10
        )
        self._pub_controller = self.create_publisher(
            ByteMultiArray, "xr_teleop/controller_data", 10
        )
        self._pub_full_body = self.create_publisher(
            ByteMultiArray, "xr_teleop/full_body", 10
        )
        self._pub_finger_joints = self.create_publisher(
            JointState, "xr_teleop/finger_joints", 10
        )

        hands = HandsSource(name="hands")
        controllers = ControllersSource(name="controllers")
        full_body = FullBodySource(name="full_body")
        locomotion = LocomotionRootCmdRetargeter(
            LocomotionRootCmdRetargeterConfig(), name="locomotion"
        )
        locomotion_connected = locomotion.connect(
            {
                "controller_left": controllers.output(ControllersSource.LEFT),
                "controller_right": controllers.output(ControllersSource.RIGHT),
            }
        )

        left_hand_retargeter = TriHandMotionControllerRetargeter(
            TriHandMotionControllerConfig(
                hand_joint_names=left_finger_joint_names, controller_side="left"
            ),
            name="trihand_left",
        )
        right_hand_retargeter = TriHandMotionControllerRetargeter(
            TriHandMotionControllerConfig(
                hand_joint_names=right_finger_joint_names, controller_side="right"
            ),
            name="trihand_right",
        )
        left_hand_connected = left_hand_retargeter.connect(
            {ControllersSource.LEFT: controllers.output(ControllersSource.LEFT)}
        )
        right_hand_connected = right_hand_retargeter.connect(
            {ControllersSource.RIGHT: controllers.output(ControllersSource.RIGHT)}
        )

        pipeline = OutputCombiner(
            {
                "hand_left": hands.output(HandsSource.LEFT),
                "hand_right": hands.output(HandsSource.RIGHT),
                "controller_left": controllers.output(ControllersSource.LEFT),
                "controller_right": controllers.output(ControllersSource.RIGHT),
                "root_command": locomotion_connected.output("root_command"),
                "full_body": full_body.output(FullBodySource.FULL_BODY),
                "finger_joints_left": left_hand_connected.output("hand_joints"),
                "finger_joints_right": right_hand_connected.output("hand_joints"),
            }
        )

        plugins: List[PluginConfig] = []
        if self._use_mock_operators:
            plugin_paths = []
            env_paths = os.environ.get("ISAAC_TELEOP_PLUGIN_PATH")
            if env_paths:
                plugin_paths.extend([Path(p) for p in env_paths.split(os.pathsep) if p])
            plugin_paths.extend(_find_plugins_dirs(Path(__file__).resolve()))
            plugins.append(
                PluginConfig(
                    plugin_name="controller_synthetic_hands",
                    plugin_root_id="synthetic_hands",
                    search_paths=plugin_paths,
                )
            )

        self._config = TeleopSessionConfig(
            app_name="TeleopRos2Publisher",
            pipeline=pipeline,
            plugins=plugins,
        )

    def _build_wrist_tfs(
        self,
        ee_msg: PoseArray,
        *,
        right_available: bool,
        left_available: bool,
        now,
    ) -> List[TransformStamped]:
        """Build wrist TF transforms from a pre-built ee_poses PoseArray (right pose at index 0, left at index 1)."""
        tfs = []

        def _get_orientation(pose: Pose) -> List[float]:
            return [
                pose.orientation.x,
                pose.orientation.y,
                pose.orientation.z,
                pose.orientation.w,
            ]

        if right_available:
            pose = ee_msg.poses[0]
            tfs.append(
                _make_transform(
                    now,
                    self._world_frame,
                    self._right_wrist_frame,
                    [pose.position.x, pose.position.y, pose.position.z],
                    _get_orientation(pose),
                )
            )
        if left_available:
            pose = ee_msg.poses[1]
            tfs.append(
                _make_transform(
                    now,
                    self._world_frame,
                    self._left_wrist_frame,
                    [pose.position.x, pose.position.y, pose.position.z],
                    _get_orientation(pose),
                )
            )
        return tfs

    def run(self) -> int:
        while rclpy.ok():
            try:
                with TeleopSession(self._config) as session:
                    self.get_logger().info("TeleopSession started successfully")
                    while rclpy.ok():
                        result = session.step()

                        now = self.get_clock().now().to_msg()
                        left_ctrl = result["controller_left"]
                        right_ctrl = result["controller_right"]

                        if self._mode == "hand_teleop":
                            left_hand = result["hand_left"]
                            right_hand = result["hand_right"]
                            # Build hand poses from hands
                            hand_msg = _build_hand_msg_from_hands(
                                left_hand,
                                right_hand,
                                now,
                                self._world_frame,
                                self._transform_rot,
                                self._transform_trans,
                            )
                            if hand_msg.poses:
                                self._pub_hand.publish(hand_msg)
                            # Build EE poses from hands
                            ee_msg = _build_ee_msg_from_hands(
                                left_hand,
                                right_hand,
                                now,
                                self._world_frame,
                                self._transform_rot,
                                self._transform_trans,
                            )
                            if ee_msg.poses:
                                self._pub_ee_pose.publish(ee_msg)
                            wrist_tfs = self._build_wrist_tfs(
                                ee_msg,
                                right_available=not right_hand.is_none,
                                left_available=not left_hand.is_none,
                                now=now,
                            )
                            if wrist_tfs:
                                self._tf_broadcaster.sendTransform(wrist_tfs)
                        elif self._mode == "controller_teleop":
                            # Build EE poses from controllers
                            ee_msg = _build_ee_msg_from_controllers(
                                left_ctrl,
                                right_ctrl,
                                now,
                                self._world_frame,
                                self._transform_rot,
                                self._transform_trans,
                            )
                            if ee_msg.poses:
                                self._pub_ee_pose.publish(ee_msg)
                            wrist_tfs = self._build_wrist_tfs(
                                ee_msg,
                                right_available=not right_ctrl.is_none,
                                left_available=not left_ctrl.is_none,
                                now=now,
                            )
                            if wrist_tfs:
                                self._tf_broadcaster.sendTransform(wrist_tfs)

                        if self._mode in ("hand_teleop", "controller_teleop"):
                            root_command = result.get("root_command")
                            if not root_command.is_none:
                                cmd = np.asarray(root_command[0])
                                twist_msg = TwistStamped()
                                twist_msg.header.stamp = now
                                twist_msg.header.frame_id = self._world_frame
                                twist_msg.twist.linear.x = float(cmd[0])
                                twist_msg.twist.linear.y = float(cmd[1])
                                twist_msg.twist.linear.z = 0.0
                                twist_msg.twist.angular.z = float(cmd[2])
                                self._pub_root_twist.publish(twist_msg)

                                pose_msg = PoseStamped()
                                pose_msg.header.stamp = now
                                pose_msg.header.frame_id = self._world_frame
                                pose_msg.pose.position.z = float(cmd[3])
                                pose_msg.pose.orientation.w = 1.0
                                self._pub_root_pose.publish(pose_msg)

                        if self._mode == "controller_teleop":
                            left_joints = result["finger_joints_left"]
                            right_joints = result["finger_joints_right"]
                            if not left_joints.is_none or not right_joints.is_none:
                                finger_joints_msg = JointState()
                                finger_joints_msg.header.stamp = now
                                finger_joints_msg.header.frame_id = self._world_frame
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
                                    _joint_names_from_group(left_joints)
                                    if not left_joints.is_none
                                    else []
                                ) + (
                                    _joint_names_from_group(right_joints)
                                    if not right_joints.is_none
                                    else []
                                )
                                finger_joints_msg.position = np.concatenate(
                                    [left_arr, right_arr]
                                ).tolist()
                                self._pub_finger_joints.publish(finger_joints_msg)

                        if self._mode in ("controller_raw", "full_body"):
                            if not left_ctrl.is_none or not right_ctrl.is_none:
                                controller_payload = _build_controller_payload(
                                    left_ctrl, right_ctrl
                                )
                                payload = msgpack.packb(
                                    controller_payload, default=mnp.encode
                                )
                                payload = tuple(bytes([a]) for a in payload)
                                controller_msg = ByteMultiArray()
                                controller_msg.data = payload
                                self._pub_controller.publish(controller_msg)

                        if self._mode == "full_body":
                            full_body_data = result["full_body"]
                            if not full_body_data.is_none:
                                body_payload = _build_full_body_payload(full_body_data)
                                payload = msgpack.packb(
                                    body_payload, default=mnp.encode
                                )
                                payload = tuple(bytes([a]) for a in payload)
                                body_msg = ByteMultiArray()
                                body_msg.data = payload
                                self._pub_full_body.publish(body_msg)

                        time.sleep(self._sleep_period_s)
            except RuntimeError as e:
                if "Failed to get OpenXR system" not in str(e):
                    raise
                self.get_logger().warn(
                    f"No XR client connected ({e}), retrying in 2s..."
                )
                time.sleep(2.0)

        return 0


def main() -> int:
    rclpy.init()
    node = None
    try:
        node = TeleopRos2Node()
        return node.run()
    finally:
        if node is not None:
            node.destroy_node()
        if rclpy.ok():
            rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
