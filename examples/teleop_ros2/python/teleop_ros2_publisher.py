#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Teleop ROS2 Reference Publisher.

Publishes teleoperation data over ROS2 topics using isaacteleop TeleopSession.
The `mode` parameter selects the teleoperation scenario and which topics are
published:

  - controller_teleop (default): ee_poses (from controller aim pose), root_twist, root_pose,
                       finger_joints (retargeted TriHand angles), and TF transforms for
                       left/right wrists
  - hand_teleop: ee_poses (from hand tracking wrist), hand (raw finger poses),
                 root_twist, root_pose, and TF transforms for left/right wrists
  - controller_raw: controller_data only
  - full_body: full_body only

Topic names (configurable via parameters):
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
import time
from typing import Dict, List, Sequence, Union

import msgpack
import msgpack_numpy as mnp
import numpy as np
import rclpy
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


# Helper functions


def _append_hand_poses(
    poses: List[Pose],
    joint_positions: np.ndarray,
    joint_orientations: np.ndarray,
) -> None:
    for joint_idx in range(
        HandJointIndex.THUMB_METACARPAL, HandJointIndex.LITTLE_TIP + 1
    ):
        poses.append(
            _to_pose(joint_positions[joint_idx], joint_orientations[joint_idx])
        )


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


# Message builders


def _build_ee_msg_from_controllers(
    left_ctrl: OptionalTensorGroup,
    right_ctrl: OptionalTensorGroup,
    now,
    frame_id: str,
) -> PoseArray:
    """Build a PoseArray with right then left controller aim poses (wrist proxy)."""
    msg = PoseArray()
    msg.header.stamp = now
    msg.header.frame_id = frame_id
    if not right_ctrl.is_none:
        pos = [float(x) for x in right_ctrl[ControllerInputIndex.AIM_POSITION]]
        ori = [float(x) for x in right_ctrl[ControllerInputIndex.AIM_ORIENTATION]]
        msg.poses.append(_to_pose(pos, ori))
    else:
        msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    if not left_ctrl.is_none:
        pos = [float(x) for x in left_ctrl[ControllerInputIndex.AIM_POSITION]]
        ori = [float(x) for x in left_ctrl[ControllerInputIndex.AIM_ORIENTATION]]
        msg.poses.append(_to_pose(pos, ori))
    else:
        msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    return msg


def _build_ee_msg_from_hands(
    left_hand: OptionalTensorGroup,
    right_hand: OptionalTensorGroup,
    now,
    frame_id: str,
) -> PoseArray:
    """Build a PoseArray with right then left hand wrist poses (EE proxy)."""
    msg = PoseArray()
    msg.header.stamp = now
    msg.header.frame_id = frame_id

    if not right_hand.is_none:
        right_positions = np.asarray(right_hand[HandInputIndex.JOINT_POSITIONS])
        right_orientations = np.asarray(right_hand[HandInputIndex.JOINT_ORIENTATIONS])
        msg.poses.append(
            _to_pose(
                right_positions[HandJointIndex.WRIST],
                right_orientations[HandJointIndex.WRIST],
            )
        )
    else:
        msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    if not left_hand.is_none:
        left_positions = np.asarray(left_hand[HandInputIndex.JOINT_POSITIONS])
        left_orientations = np.asarray(left_hand[HandInputIndex.JOINT_ORIENTATIONS])
        msg.poses.append(
            _to_pose(
                left_positions[HandJointIndex.WRIST],
                left_orientations[HandJointIndex.WRIST],
            )
        )
    else:
        msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    return msg


def _build_hand_msg_from_hands(
    left_hand: OptionalTensorGroup,
    right_hand: OptionalTensorGroup,
    now,
    frame_id: str,
) -> PoseArray:
    """Build a PoseArray with right then left hand finger joints."""
    msg = PoseArray()
    msg.header.stamp = now
    msg.header.frame_id = frame_id

    if not right_hand.is_none:
        right_positions = np.asarray(right_hand[HandInputIndex.JOINT_POSITIONS])
        right_orientations = np.asarray(right_hand[HandInputIndex.JOINT_ORIENTATIONS])
        _append_hand_poses(msg.poses, right_positions, right_orientations)
    else:
        for _ in range(HandJointIndex.THUMB_METACARPAL, HandJointIndex.LITTLE_TIP + 1):
            msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    if not left_hand.is_none:
        left_positions = np.asarray(left_hand[HandInputIndex.JOINT_POSITIONS])
        left_orientations = np.asarray(left_hand[HandInputIndex.JOINT_ORIENTATIONS])
        _append_hand_poses(msg.poses, left_positions, left_orientations)
    else:
        for _ in range(HandJointIndex.THUMB_METACARPAL, HandJointIndex.LITTLE_TIP + 1):
            msg.poses.append(_to_pose([0.0, 0.0, 0.0]))

    return msg


def _build_wrist_tfs(
    ee_msg: PoseArray,
    right_available: bool,
    left_available: bool,
    now,
    world_frame: str,
    right_wrist_frame: str,
    left_wrist_frame: str,
) -> List[TransformStamped]:
    """Build wrist TF transforms from a pre-built ee_poses PoseArray (right pose at index 0, left at index 1)."""
    tfs = []
    if right_available:
        pose = ee_msg.poses[0]
        tfs.append(
            _make_transform(
                now,
                world_frame,
                right_wrist_frame,
                [pose.position.x, pose.position.y, pose.position.z],
                [
                    pose.orientation.x,
                    pose.orientation.y,
                    pose.orientation.z,
                    pose.orientation.w,
                ],
            )
        )
    if left_available:
        pose = ee_msg.poses[1]
        tfs.append(
            _make_transform(
                now,
                world_frame,
                left_wrist_frame,
                [pose.position.x, pose.position.y, pose.position.z],
                [
                    pose.orientation.x,
                    pose.orientation.y,
                    pose.orientation.z,
                    pose.orientation.w,
                ],
            )
        )
    return tfs


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


_TRIHAND_JOINT_NAMES = [
    "thumb_rotation",
    "thumb_proximal",
    "thumb_distal",
    "index_proximal",
    "index_distal",
    "middle_proximal",
    "middle_distal",
]
_FINGER_JOINT_NAMES = [f"left_{n}" for n in _TRIHAND_JOINT_NAMES] + [
    f"right_{n}" for n in _TRIHAND_JOINT_NAMES
]


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


class TeleopRos2PublisherNode(Node):
    """ROS 2 node that publishes teleop data to configurable topics."""

    def __init__(self) -> None:
        super().__init__("teleop_ros2_publisher")

        self.declare_parameter("hand_topic", "xr_teleop/hand")
        self.declare_parameter("ee_pose_topic", "xr_teleop/ee_poses")
        self.declare_parameter("root_twist_topic", "xr_teleop/root_twist")
        self.declare_parameter("root_pose_topic", "xr_teleop/root_pose")
        self.declare_parameter("controller_topic", "xr_teleop/controller_data")
        self.declare_parameter("full_body_topic", "xr_teleop/full_body")
        self.declare_parameter("finger_joints_topic", "xr_teleop/finger_joints")
        self.declare_parameter("rate_hz", 60.0)
        self.declare_parameter("mode", "controller_teleop")
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

        self._hand_topic = (
            self.get_parameter("hand_topic").get_parameter_value().string_value
        )
        self._ee_pose_topic = (
            self.get_parameter("ee_pose_topic").get_parameter_value().string_value
        )
        self._root_twist_topic = (
            self.get_parameter("root_twist_topic").get_parameter_value().string_value
        )
        self._root_pose_topic = (
            self.get_parameter("root_pose_topic").get_parameter_value().string_value
        )
        self._controller_topic = (
            self.get_parameter("controller_topic").get_parameter_value().string_value
        )
        self._full_body_topic = (
            self.get_parameter("full_body_topic").get_parameter_value().string_value
        )
        self._finger_joints_topic = (
            self.get_parameter("finger_joints_topic").get_parameter_value().string_value
        )
        rate_hz = self.get_parameter("rate_hz").get_parameter_value().double_value
        if rate_hz <= 0 or not math.isfinite(rate_hz):
            raise ValueError("Parameter 'rate_hz' must be > 0")
        self._sleep_period_s = 1.0 / rate_hz
        mode = self.get_parameter("mode").get_parameter_value().string_value
        if mode not in _TELEOP_MODES:
            raise ValueError(
                f"Parameter 'mode' must be one of {_TELEOP_MODES}, got {mode!r}"
            )
        self._mode = mode
        self._world_frame = (
            self.get_parameter("world_frame").get_parameter_value().string_value
        )
        self._right_wrist_frame = (
            self.get_parameter("right_wrist_frame").get_parameter_value().string_value
        )
        self._left_wrist_frame = (
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

        self._tf_broadcaster = TransformBroadcaster(self)

        self._pub_hand = self.create_publisher(PoseArray, self._hand_topic, 10)
        self._pub_ee_pose = self.create_publisher(PoseArray, self._ee_pose_topic, 10)
        self._pub_root_twist = self.create_publisher(
            TwistStamped, self._root_twist_topic, 10
        )
        self._pub_root_pose = self.create_publisher(
            PoseStamped, self._root_pose_topic, 10
        )
        self._pub_controller = self.create_publisher(
            ByteMultiArray, self._controller_topic, 10
        )
        self._pub_full_body = self.create_publisher(
            ByteMultiArray, self._full_body_topic, 10
        )
        self._pub_finger_joints = self.create_publisher(
            JointState, self._finger_joints_topic, 10
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
                hand_joint_names=_TRIHAND_JOINT_NAMES, controller_side="left"
            ),
            name="trihand_left",
        )
        right_hand_retargeter = TriHandMotionControllerRetargeter(
            TriHandMotionControllerConfig(
                hand_joint_names=_TRIHAND_JOINT_NAMES, controller_side="right"
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

        self._config = TeleopSessionConfig(
            app_name="TeleopRos2Publisher",
            pipeline=pipeline,
            plugins=plugins,
        )

    def run(self) -> int:
        while rclpy.ok():
            try:
                with TeleopSession(self._config) as session:
                    while rclpy.ok():
                        result = session.step()

                        now = self.get_clock().now().to_msg()
                        left_ctrl = result["controller_left"]
                        right_ctrl = result["controller_right"]

                        if self._mode == "hand_teleop":
                            left_hand = result["hand_left"]
                            right_hand = result["hand_right"]
                            hand_msg = _build_hand_msg_from_hands(
                                left_hand, right_hand, now, self._world_frame
                            )
                            if hand_msg.poses:
                                self._pub_hand.publish(hand_msg)
                            ee_msg = _build_ee_msg_from_hands(
                                left_hand, right_hand, now, self._world_frame
                            )
                            if ee_msg.poses:
                                self._pub_ee_pose.publish(ee_msg)
                            wrist_tfs = _build_wrist_tfs(
                                ee_msg,
                                not right_hand.is_none,
                                not left_hand.is_none,
                                now,
                                self._world_frame,
                                self._right_wrist_frame,
                                self._left_wrist_frame,
                            )
                            if wrist_tfs:
                                self._tf_broadcaster.sendTransform(wrist_tfs)
                        elif self._mode == "controller_teleop":
                            ee_msg = _build_ee_msg_from_controllers(
                                left_ctrl, right_ctrl, now, self._world_frame
                            )
                            if ee_msg.poses:
                                self._pub_ee_pose.publish(ee_msg)
                            wrist_tfs = _build_wrist_tfs(
                                ee_msg,
                                not right_ctrl.is_none,
                                not left_ctrl.is_none,
                                now,
                                self._world_frame,
                                self._right_wrist_frame,
                                self._left_wrist_frame,
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
                                    list(
                                        _FINGER_JOINT_NAMES[: len(_TRIHAND_JOINT_NAMES)]
                                    )
                                    if not left_joints.is_none
                                    else []
                                ) + (
                                    list(
                                        _FINGER_JOINT_NAMES[len(_TRIHAND_JOINT_NAMES) :]
                                    )
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
        node = TeleopRos2PublisherNode()
        return node.run()
    finally:
        if node is not None:
            node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
