#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Teleop ROS2 Reference Publisher.

Publishes teleoperation data over ROS2 topics using isaacteleop TeleopSession:
  - xr_teleop/hand (PoseArray): [right_wrist, left_wrist, finger_joint_poses...]
  - xr_teleop/root_twist (TwistStamped): root velocity command
  - xr_teleop/root_pose (PoseStamped): root pose command (height only)
  - xr_teleop/controller_data (ByteMultiArray): msgpack-encoded controller data
  - xr_teleop/full_body (ByteMultiArray): msgpack-encoded full body tracking data
"""

import math
import os
import time
from pathlib import Path
from typing import Dict, List

import msgpack
import msgpack_numpy as mnp
import numpy as np
import rclpy
from geometry_msgs.msg import Pose, PoseArray, PoseStamped, TwistStamped
from rclpy.node import Node
from std_msgs.msg import ByteMultiArray

from isaacteleop.retargeting_engine.deviceio_source_nodes import (
    ControllersSource,
    FullBodySource,
    HandsSource,
)
from isaacteleop.retargeting_engine.interface import OptionalTensorGroup, OutputCombiner
from isaacteleop.retargeting_engine.retargeters import (
    LocomotionRootCmdRetargeter,
    LocomotionRootCmdRetargeterConfig,
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


def _find_plugins_dirs(start: Path) -> List[Path]:
    candidates = []
    for parent in [start] + list(start.parents):
        plugin_dir = parent / "plugins"
        if plugin_dir.is_dir():
            candidates.append(plugin_dir)
            break
    return candidates


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


_BODY_JOINT_NAMES = [e.name for e in BodyJointPicoIndex]


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


class TeleopRos2PublisherNode(Node):
    """ROS 2 node that publishes teleop data to configurable topics."""

    def __init__(self) -> None:
        super().__init__("teleop_ros2_publisher")

        self.declare_parameter("hand_topic", "xr_teleop/hand")
        self.declare_parameter("twist_topic", "xr_teleop/root_twist")
        self.declare_parameter("pose_topic", "xr_teleop/root_pose")
        self.declare_parameter("controller_topic", "xr_teleop/controller_data")
        self.declare_parameter("full_body_topic", "xr_teleop/full_body")
        self.declare_parameter("frame_id", "world")
        self.declare_parameter("rate_hz", 60.0)
        self.declare_parameter("use_mock_operators", value=False)

        self._hand_topic = (
            self.get_parameter("hand_topic").get_parameter_value().string_value
        )
        self._twist_topic = (
            self.get_parameter("twist_topic").get_parameter_value().string_value
        )
        self._pose_topic = (
            self.get_parameter("pose_topic").get_parameter_value().string_value
        )
        self._controller_topic = (
            self.get_parameter("controller_topic").get_parameter_value().string_value
        )
        self._full_body_topic = (
            self.get_parameter("full_body_topic").get_parameter_value().string_value
        )
        self._frame_id = (
            self.get_parameter("frame_id").get_parameter_value().string_value
        )
        rate_hz = self.get_parameter("rate_hz").get_parameter_value().double_value
        if rate_hz <= 0 or not math.isfinite(rate_hz):
            raise ValueError("Parameter 'rate_hz' must be > 0")
        self._sleep_period_s = 1.0 / rate_hz
        self._use_mock_operators = (
            self.get_parameter("use_mock_operators").get_parameter_value().bool_value
        )

        self._pub_hand = self.create_publisher(PoseArray, self._hand_topic, 10)
        self._pub_twist = self.create_publisher(TwistStamped, self._twist_topic, 10)
        self._pub_pose = self.create_publisher(PoseStamped, self._pose_topic, 10)
        self._pub_controller = self.create_publisher(
            ByteMultiArray, self._controller_topic, 10
        )
        self._pub_full_body = self.create_publisher(
            ByteMultiArray, self._full_body_topic, 10
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

        pipeline = OutputCombiner(
            {
                "hand_left": hands.output(HandsSource.LEFT),
                "hand_right": hands.output(HandsSource.RIGHT),
                "controller_left": controllers.output(ControllersSource.LEFT),
                "controller_right": controllers.output(ControllersSource.RIGHT),
                "root_command": locomotion_connected.output("root_command"),
                "full_body": full_body.output(FullBodySource.FULL_BODY),
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

    def run(self) -> int:
        while rclpy.ok():
            try:
                with TeleopSession(self._config) as session:
                    while rclpy.ok():
                        result = session.step()

                        now = self.get_clock().now().to_msg()
                        hand_msg = PoseArray()
                        hand_msg.header.stamp = now
                        hand_msg.header.frame_id = self._frame_id

                        left_hand = result["hand_left"]
                        right_hand = result["hand_right"]

                        if not right_hand.is_none:
                            right_positions = np.asarray(
                                right_hand[HandInputIndex.JOINT_POSITIONS]
                            )
                            right_orientations = np.asarray(
                                right_hand[HandInputIndex.JOINT_ORIENTATIONS]
                            )
                            hand_msg.poses.append(
                                _to_pose(
                                    right_positions[HandJointIndex.WRIST],
                                    right_orientations[HandJointIndex.WRIST],
                                )
                            )
                        if not left_hand.is_none:
                            left_positions = np.asarray(
                                left_hand[HandInputIndex.JOINT_POSITIONS]
                            )
                            left_orientations = np.asarray(
                                left_hand[HandInputIndex.JOINT_ORIENTATIONS]
                            )
                            hand_msg.poses.append(
                                _to_pose(
                                    left_positions[HandJointIndex.WRIST],
                                    left_orientations[HandJointIndex.WRIST],
                                )
                            )

                        if not right_hand.is_none:
                            _append_hand_poses(
                                hand_msg.poses, right_positions, right_orientations
                            )
                        if not left_hand.is_none:
                            _append_hand_poses(
                                hand_msg.poses, left_positions, left_orientations
                            )

                        if hand_msg.poses:
                            self._pub_hand.publish(hand_msg)

                        root_command = result["root_command"]
                        cmd = np.asarray(root_command[0])
                        twist_msg = TwistStamped()
                        twist_msg.header.stamp = now
                        twist_msg.header.frame_id = self._frame_id
                        twist_msg.twist.linear.x = float(cmd[0])
                        twist_msg.twist.linear.y = float(cmd[1])
                        twist_msg.twist.linear.z = 0.0
                        twist_msg.twist.angular.z = float(cmd[2])
                        self._pub_twist.publish(twist_msg)

                        pose_msg = PoseStamped()
                        pose_msg.header.stamp = now
                        pose_msg.header.frame_id = self._frame_id
                        pose_msg.pose.position.z = float(cmd[3])
                        pose_msg.pose.orientation.w = 1.0
                        self._pub_pose.publish(pose_msg)

                        left_ctrl = result["controller_left"]
                        right_ctrl = result["controller_right"]
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

                        full_body_data = result["full_body"]
                        if not full_body_data.is_none:
                            body_payload = _build_full_body_payload(full_body_data)
                            payload = msgpack.packb(body_payload, default=mnp.encode)
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
