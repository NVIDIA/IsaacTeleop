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

import argparse
import os
import time
from pathlib import Path
from typing import Dict, List, Optional

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
from isaacteleop.retargeting_engine.interface import OutputCombiner
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
    left_ctrl: Optional[np.ndarray],
    right_ctrl: Optional[np.ndarray],
) -> Dict:
    def _as_list(ctrl, index):
        if ctrl is None:
            return [0.0, 0.0, 0.0]
        return [float(x) for x in ctrl[index]]

    def _as_quat(ctrl, index):
        if ctrl is None:
            return [1.0, 0.0, 0.0, 0.0]
        return [float(x) for x in ctrl[index]]

    def _as_float(ctrl, index):
        if ctrl is None:
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
        "left_is_active": bool(_as_float(left_ctrl, ControllerInputIndex.IS_ACTIVE)),
        "right_is_active": bool(_as_float(right_ctrl, ControllerInputIndex.IS_ACTIVE)),
    }


_BODY_JOINT_NAMES = [e.name for e in BodyJointPicoIndex]


def _build_full_body_payload(full_body: np.ndarray) -> Dict:
    positions = np.asarray(full_body[FullBodyInputIndex.JOINT_POSITIONS])
    orientations = np.asarray(full_body[FullBodyInputIndex.JOINT_ORIENTATIONS])
    valid = np.asarray(full_body[FullBodyInputIndex.JOINT_VALID])

    return {
        "timestamp": time.time_ns(),
        "is_active": bool(full_body[FullBodyInputIndex.IS_ACTIVE]),
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Teleop ROS2 reference publisher")
    parser.add_argument("--hand-topic", default="xr_teleop/hand")
    parser.add_argument("--twist-topic", default="xr_teleop/root_twist")
    parser.add_argument("--pose-topic", default="xr_teleop/root_pose")
    parser.add_argument("--controller-topic", default="xr_teleop/controller_data")
    parser.add_argument("--full-body-topic", default="xr_teleop/full_body")
    parser.add_argument("--frame-id", default="world")
    parser.add_argument("--rate-hz", type=float, default=60.0)
    parser.add_argument("--use-mock-operators", action="store_true")
    args = parser.parse_args()
    sleep_period_s = 1.0 / max(args.rate_hz, 1e-3)

    rclpy.init()
    node = Node("teleop_ros2_publisher")

    pub_hand = node.create_publisher(PoseArray, args.hand_topic, 10)
    pub_twist = node.create_publisher(TwistStamped, args.twist_topic, 10)
    pub_pose = node.create_publisher(PoseStamped, args.pose_topic, 10)
    pub_controller = node.create_publisher(ByteMultiArray, args.controller_topic, 10)
    pub_full_body = node.create_publisher(ByteMultiArray, args.full_body_topic, 10)

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

    plugins = []
    if args.use_mock_operators:
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

    config = TeleopSessionConfig(
        app_name="TeleopRos2Publisher",
        pipeline=pipeline,
        plugins=plugins,
    )

    with TeleopSession(config) as session:
        while rclpy.ok():
            result = session.step()

            now = node.get_clock().now().to_msg()
            hand_msg = PoseArray()
            hand_msg.header.stamp = now
            hand_msg.header.frame_id = args.frame_id

            left_hand = result.get("hand_left")
            right_hand = result.get("hand_right")

            if right_hand is not None and right_hand[HandInputIndex.IS_ACTIVE]:
                right_positions = np.asarray(right_hand[HandInputIndex.JOINT_POSITIONS])
                right_orientations = np.asarray(
                    right_hand[HandInputIndex.JOINT_ORIENTATIONS]
                )
                hand_msg.poses.append(
                    _to_pose(
                        right_positions[HandJointIndex.WRIST],
                        right_orientations[HandJointIndex.WRIST],
                    )
                )
            if left_hand is not None and left_hand[HandInputIndex.IS_ACTIVE]:
                left_positions = np.asarray(left_hand[HandInputIndex.JOINT_POSITIONS])
                left_orientations = np.asarray(
                    left_hand[HandInputIndex.JOINT_ORIENTATIONS]
                )
                hand_msg.poses.append(
                    _to_pose(
                        left_positions[HandJointIndex.WRIST],
                        left_orientations[HandJointIndex.WRIST],
                    )
                )

            if right_hand is not None and right_hand[HandInputIndex.IS_ACTIVE]:
                _append_hand_poses(hand_msg.poses, right_positions, right_orientations)
            if left_hand is not None and left_hand[HandInputIndex.IS_ACTIVE]:
                _append_hand_poses(hand_msg.poses, left_positions, left_orientations)

            if hand_msg.poses:
                pub_hand.publish(hand_msg)

            root_command = result.get("root_command")
            if root_command is not None:
                cmd = np.asarray(root_command[0])
                twist_msg = TwistStamped()
                twist_msg.header.stamp = now
                twist_msg.header.frame_id = args.frame_id
                twist_msg.twist.linear.x = float(cmd[0])
                twist_msg.twist.linear.y = float(cmd[1])
                twist_msg.twist.linear.z = 0.0
                twist_msg.twist.angular.z = float(cmd[2])
                pub_twist.publish(twist_msg)

                pose_msg = PoseStamped()
                pose_msg.header.stamp = now
                pose_msg.header.frame_id = args.frame_id
                pose_msg.pose.position.z = float(cmd[3])
                pose_msg.pose.orientation.w = 1.0
                pub_pose.publish(pose_msg)

            left_ctrl = result.get("controller_left")
            right_ctrl = result.get("controller_right")
            left_active = left_ctrl is not None and bool(
                left_ctrl[ControllerInputIndex.IS_ACTIVE]
            )
            right_active = right_ctrl is not None and bool(
                right_ctrl[ControllerInputIndex.IS_ACTIVE]
            )
            if left_active or right_active:
                controller_payload = _build_controller_payload(left_ctrl, right_ctrl)
                payload = msgpack.packb(controller_payload, default=mnp.encode)
                payload = tuple(bytes([a]) for a in payload)
                controller_msg = ByteMultiArray()
                controller_msg.data = payload
                pub_controller.publish(controller_msg)

            full_body_data = result.get("full_body")
            if full_body_data is not None and bool(
                full_body_data[FullBodyInputIndex.IS_ACTIVE]
            ):
                body_payload = _build_full_body_payload(full_body_data)
                payload = msgpack.packb(body_payload, default=mnp.encode)
                payload = tuple(bytes([a]) for a in payload)
                body_msg = ByteMultiArray()
                body_msg.data = payload
                pub_full_body.publish(body_msg)

            time.sleep(sleep_period_s)

    node.destroy_node()
    rclpy.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
