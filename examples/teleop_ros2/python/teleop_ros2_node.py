#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Teleop ROS2 Reference Node.

Publishes teleoperation data over ROS2 topics using isaacteleop TeleopSession.
The `mode` parameter selects the teleoperation scenario and which topics are
published:

  - controller_teleop (default): ee_pose (from controller aim poses),
                       root_twist, root_pose, finger_joints
                       (retargeted TriHand angles), controller_data, head_pose,
                       and TF transforms for left/right wrists and head
  - hand_teleop: ee_pose (from hand tracking wrists), hand (named left and
                 right joint poses),
                 finger_joints (retargeted Sharpa joint angles),
                 root_twist/root_pose (from foot pedal locomotion), head_pose,
                 and TF transforms for left/right wrists and head
  - controller_raw: controller_data only
  - full_body: full_body and controller_data

Topic names (remappable via ROS 2 remapping):
  - xr_teleop/hand (NamedPoseArray): named left and right hand joint poses
  - xr_teleop/ee_pose (NamedPoseArray): named left and right EE poses
  - xr_teleop/root_twist (TwistStamped): root velocity command
  - xr_teleop/root_pose (PoseStamped): root pose command (height only)
  - xr_teleop/head_pose (PoseStamped): head pose
  - xr_teleop/controller_data (ByteMultiArray): msgpack-encoded controller data
  - xr_teleop/full_body (ByteMultiArray): msgpack-encoded full body tracking data
  - xr_teleop/finger_joints (JointState): retargeted finger joint angles

TF frames published in hand_teleop and controller_teleop modes (configurable via parameters):
  - world_frame -> right_wrist_frame
  - world_frame -> left_wrist_frame
  - world_frame -> head_frame
"""

import time
from typing import List

import msgpack
import msgpack_numpy as mnp
import numpy as np
import rclpy
from geometry_msgs.msg import (
    Pose,
    PoseStamped,
    TransformStamped,
    TwistStamped,
)
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import ByteMultiArray
from teleop_ros2_interfaces.msg import NamedPoseArray
from tf2_ros import TransformBroadcaster

from isaacteleop.cloudxr import CloudXRLauncher
from isaacteleop.teleop_session_manager import SessionMode, TeleopSession
from geometry import make_transform
from messages import (
    build_controller_payload,
    build_ee_msg_from_controllers,
    build_ee_msg_from_hands,
    build_finger_joints_msg,
    build_full_body_payload,
    build_hand_msg,
    build_head_msg,
)
from node_parameters import (
    NodeParameters,
    create_node_parameters,
)
from session_config import build_session_config
from tensor_group_helpers import (
    head_is_valid,
)


class TeleopRos2Node(Node):
    """ROS 2 node that publishes teleop data."""

    def __init__(self) -> None:
        super().__init__("teleop_ros2_node")
        self._params: NodeParameters = create_node_parameters(self)
        self._tf_broadcaster = TransformBroadcaster(self)
        self._create_publishers()
        self._config = build_session_config(self._params)

    def _build_wrist_tfs(
        self,
        ee_msg: NamedPoseArray,
    ) -> List[TransformStamped]:
        """Build wrist TF transforms from valid EE pose entries."""
        tfs = []
        wrist_frames = {
            "left": self._params.left_wrist_frame,
            "right": self._params.right_wrist_frame,
        }

        def _get_orientation(pose: Pose) -> List[float]:
            return [
                pose.orientation.x,
                pose.orientation.y,
                pose.orientation.z,
                pose.orientation.w,
            ]

        for side, pose, is_valid in zip(ee_msg.name, ee_msg.pose, ee_msg.is_valid):
            if not is_valid:
                continue
            tfs.append(
                make_transform(
                    ee_msg.header.stamp,
                    ee_msg.header.frame_id,
                    wrist_frames[side],
                    [pose.position.x, pose.position.y, pose.position.z],
                    _get_orientation(pose),
                )
            )
        return tfs

    def _create_publishers(self) -> None:
        self._pub_hand = self.create_publisher(NamedPoseArray, "xr_teleop/hand", 10)
        self._pub_ee_pose = self.create_publisher(
            NamedPoseArray, "xr_teleop/ee_pose", 10
        )
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
        self._pub_head = self.create_publisher(PoseStamped, "xr_teleop/head_pose", 10)

    def _publish_ee_pose_from_controllers(self, result: dict, now) -> None:
        left_ctrl = result["controller_left"]
        right_ctrl = result["controller_right"]
        ee_pose_msg = build_ee_msg_from_controllers(
            left_ctrl,
            right_ctrl,
            now,
            self._params.world_frame,
            self._params.transform_rotation,
            self._params.transform_translation,
            self._params.controller_uses_hands_source,
        )
        self._pub_ee_pose.publish(ee_pose_msg)
        wrist_tfs = self._build_wrist_tfs(ee_pose_msg)
        if wrist_tfs:
            self._tf_broadcaster.sendTransform(wrist_tfs)

    def _publish_controller_payload(self, result: dict) -> None:
        if self._params.mode not in (
            "controller_raw",
            "controller_teleop",
            "full_body",
        ):
            return

        left_ctrl = result["controller_left"]
        right_ctrl = result["controller_right"]
        if left_ctrl.is_none and right_ctrl.is_none:
            return

        controller_payload = build_controller_payload(left_ctrl, right_ctrl)
        payload = msgpack.packb(controller_payload, default=mnp.encode)
        controller_msg = ByteMultiArray()
        controller_msg.data = tuple(bytes([a]) for a in payload)
        self._pub_controller.publish(controller_msg)

    def _publish_finger_joints(self, result: dict, now) -> None:
        if self._params.mode not in ("controller_teleop", "hand_teleop"):
            return

        finger_joints_msg = build_finger_joints_msg(
            result["finger_joints_left"],
            result["finger_joints_right"],
            now,
            self._params.world_frame,
        )
        if finger_joints_msg is not None:
            self._pub_finger_joints.publish(finger_joints_msg)

    def _publish_full_body_payload(self, result: dict) -> None:
        if self._params.mode != "full_body":
            return

        full_body_data = result["full_body"]
        if full_body_data.is_none:
            return

        body_payload = build_full_body_payload(full_body_data)
        payload = msgpack.packb(body_payload, default=mnp.encode)
        body_msg = ByteMultiArray()
        body_msg.data = tuple(bytes([a]) for a in payload)
        self._pub_full_body.publish(body_msg)

    def _publish_hand_poses(self, result: dict, now) -> None:
        hand_msg = build_hand_msg(
            result["hand_left"],
            result["hand_right"],
            now,
            self._params.world_frame,
            self._params.transform_rotation,
            self._params.transform_translation,
        )
        self._pub_hand.publish(hand_msg)

    def _publish_ee_pose_from_hands(self, result: dict, now) -> None:
        left_hand = result["hand_left"]
        right_hand = result["hand_right"]
        ee_pose_msg = build_ee_msg_from_hands(
            left_hand,
            right_hand,
            now,
            self._params.world_frame,
            self._params.transform_rotation,
            self._params.transform_translation,
        )
        self._pub_ee_pose.publish(ee_pose_msg)
        wrist_tfs = self._build_wrist_tfs(ee_pose_msg)
        if wrist_tfs:
            self._tf_broadcaster.sendTransform(wrist_tfs)

    def _publish_head(self, result: dict, now) -> None:
        if self._params.mode not in ("controller_teleop", "hand_teleop"):
            return

        head = result["head"]
        if not head_is_valid(head):
            return

        head_msg = build_head_msg(
            head,
            now,
            self._params.world_frame,
            self._params.transform_rotation,
            self._params.transform_translation,
        )
        if head_msg is None:
            return

        self._pub_head.publish(head_msg)
        pose = head_msg.pose
        head_tf = make_transform(
            now,
            self._params.world_frame,
            self._params.head_frame,
            [pose.position.x, pose.position.y, pose.position.z],
            [
                pose.orientation.x,
                pose.orientation.y,
                pose.orientation.z,
                pose.orientation.w,
            ],
        )
        self._tf_broadcaster.sendTransform(head_tf)

    def _publish_root_command(self, result: dict, now) -> None:
        if self._params.mode not in ("hand_teleop", "controller_teleop"):
            return

        root_command = result["root_command"]
        if root_command.is_none:
            return

        cmd = np.asarray(root_command[0])
        twist_msg = TwistStamped()
        twist_msg.header.stamp = now
        twist_msg.header.frame_id = self._params.world_frame
        twist_msg.twist.linear.x = float(cmd[0])
        twist_msg.twist.linear.y = float(cmd[1])
        twist_msg.twist.linear.z = 0.0
        twist_msg.twist.angular.z = float(cmd[2])
        self._pub_root_twist.publish(twist_msg)

        pose_msg = PoseStamped()
        pose_msg.header.stamp = now
        pose_msg.header.frame_id = self._params.world_frame
        pose_msg.pose.position.z = float(cmd[3])
        pose_msg.pose.orientation.w = 1.0
        self._pub_root_pose.publish(pose_msg)

    def _run_session_loop(self, launcher: CloudXRLauncher | None = None) -> int:
        while rclpy.ok():
            # Confirm the runtime/WSS proxy is alive before every session
            # attempt. This also guards the no-client retry path below: each
            # retry is a new iteration here, which never reaches the inner
            # per-step check, so a dead runtime surfaces as an error instead of
            # an infinite retry.
            if launcher is not None:
                launcher.health_check()
            try:
                with TeleopSession(self._config) as session:
                    self.get_logger().info("TeleopSession started successfully")
                    while rclpy.ok():
                        # Detect a mid-session runtime death promptly while a
                        # client is actively streaming (the outer-loop check
                        # only runs between session attempts).
                        if launcher is not None:
                            launcher.health_check()

                        result = session.step()

                        # Keep ROS time and other callbacks updated in this
                        # manual loop so stamped messages progress with /clock.
                        rclpy.spin_once(self, timeout_sec=0.0)

                        now = self.get_clock().now().to_msg()

                        if self._params.mode == "hand_teleop":
                            self._publish_ee_pose_from_hands(result, now)
                        elif self._params.mode == "controller_teleop":
                            self._publish_ee_pose_from_controllers(result, now)
                        if (
                            self._params.mode == "hand_teleop"
                            or self._params.controller_uses_hands_source
                        ):
                            self._publish_hand_poses(result, now)

                        self._publish_root_command(result, now)
                        self._publish_finger_joints(result, now)
                        self._publish_head(result, now)
                        self._publish_controller_payload(result)
                        self._publish_full_body_payload(result)

                        time.sleep(self._params.sleep_period_s)
            except RuntimeError as e:
                if "Failed to get OpenXR system" not in str(e):
                    raise
                # The CloudXR runtime is up but no headset/WebXR client has
                # connected yet, so xrGetSystem reports no HMD. Keep the
                # runtime alive (launcher stays open) and retry the session.
                self.get_logger().warn(
                    f"No XR client connected ({e}), retrying in 2s..."
                )
                time.sleep(2.0)

        return 0

    def run(self) -> int:
        # MCAP replay reads recorded tracker data and needs no live runtime; a
        # live session needs the CloudXR runtime + WSS proxy, which the node now
        # owns in-process via CloudXRLauncher (no separate runtime process).
        if self._params.session_mode != SessionMode.LIVE:
            return self._run_session_loop()

        with CloudXRLauncher(
            install_dir=self._params.cloudxr_params.install_dir,
            env_config=self._params.cloudxr_params.env_config,
            accept_eula=self._params.cloudxr_params.accept_eula,
            setup_oob=self._params.cloudxr_params.setup_oob,
            usb_local=self._params.cloudxr_params.usb_local,
            host_client=True,
        ) as launcher:
            self.get_logger().info(
                "CloudXR runtime and WSS proxy started "
                f"(WSS log: {launcher.wss_log_path})"
            )
            return self._run_session_loop(launcher)


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
