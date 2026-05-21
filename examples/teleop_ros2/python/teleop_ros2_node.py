#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Teleop ROS2 Reference Node.

Publishes teleoperation data over ROS2 topics using isaacteleop TeleopSession.
The `mode` parameter selects the teleoperation scenario and which topics are
published:

  - controller_teleop (default): ee_poses (from controller aim pose), root_twist,
                       root_pose, finger_joints (retargeted TriHand angles),
                       controller_data, and TF transforms for left/right wrists
  - hand_teleop: ee_poses (from hand tracking wrist), hand (finger joint poses),
                 finger_joints (retargeted Sharpa joint angles),
                 root_twist/root_pose (from foot pedal locomotion), and TF
                 transforms for left/right wrists
  - controller_raw: controller_data only
  - full_body: full_body and controller_data

Topic names (remappable via ROS 2 remapping):
  - xr_teleop/hand (PoseArray): [finger_joint_poses...]
  - xr_teleop/ee_poses (PoseArray): [left_ee, right_ee]
  - xr_teleop/root_twist (TwistStamped): root velocity command
  - xr_teleop/root_pose (PoseStamped): root pose command (height only)
  - xr_teleop/controller_data (ByteMultiArray): msgpack-encoded controller data
  - xr_teleop/full_body (ByteMultiArray): msgpack-encoded full body tracking data
  - xr_teleop/finger_joints (JointState): retargeted finger joint angles

TF frames published in hand_teleop and controller_teleop modes (configurable via parameters):
  - world_frame -> right_wrist_frame
  - world_frame -> left_wrist_frame
"""

import math
import time
from pathlib import Path
from typing import List

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
from rcl_interfaces.msg import ParameterDescriptor, ParameterType
from rclpy.node import Node
from rclpy.parameter import Parameter
from sensor_msgs.msg import JointState
from std_msgs.msg import ByteMultiArray
from tf2_ros import TransformBroadcaster

from isaacteleop.deviceio import McapReplayConfig
from isaacteleop.retargeting_engine.deviceio_source_nodes.pedals_source import (
    DEFAULT_PEDAL_COLLECTION_ID,
)
from isaacteleop.teleop_session_manager import SessionMode, TeleopSession
from assets import resolve_config_asset_root
from constants import (
    HAND_RETARGETERS,
    TELEOP_MODES,
    HandRetargeter,
    resolve_hand_retargeter,
    uses_hands_source_for_controller,
)
from geometry import make_transform
from messages import (
    build_controller_payload,
    build_ee_msg_from_controllers,
    build_ee_msg_from_hands,
    build_finger_joints_msg,
    build_full_body_payload,
    build_hand_msg_from_hands,
    controller_aim_is_valid,
    hand_wrist_is_valid,
)
from session_config import (
    TeleopRos2SessionConfigContext,
    build_session_config,
)


# Helper functions


def _make_unset_string_array_parameter_empty(node: Node, parameter: Parameter) -> None:
    if parameter.type_ != Parameter.Type.NOT_SET:
        return
    node.set_parameters([Parameter(parameter.name, Parameter.Type.STRING_ARRAY, [])])


def _resolve_finger_joint_name_aliases(
    parameter_name: str,
    names: List[str],
) -> List[str] | None:
    for index, joint_name in enumerate(names, start=1):
        if not joint_name.strip():
            raise ValueError(
                f"Parameter '{parameter_name}' entry {index} must be a non-empty string"
            )

    return names or None


class TeleopRos2Node(Node):
    """ROS 2 node that publishes teleop data."""

    def __init__(self) -> None:
        super().__init__("teleop_ros2_node")

        self.declare_parameter("mode", "controller_teleop")
        self.declare_parameter("rate_hz", 60.0)
        self.declare_parameter(
            "pedal_collection_id",
            DEFAULT_PEDAL_COLLECTION_ID,
            ParameterDescriptor(
                description=(
                    "Tensor collection ID used for hand_teleop foot pedal locomotion. "
                    "Must match the pedal pusher or reader collection_id."
                )
            ),
        )
        self.declare_parameter(
            "hand_retargeter",
            HandRetargeter.MODE_DEFAULT.value,
            ParameterDescriptor(
                description=(
                    "Hand retargeter backend. 'mode_default' resolves to "
                    "'trihand' in controller_teleop and 'dexpilot' in "
                    "hand_teleop. Valid values: 'mode_default', 'trihand', "
                    "'pink_ik', or 'dexpilot'."
                )
            ),
        )
        self.declare_parameter(
            "config_asset_root",
            "",
            ParameterDescriptor(
                type=ParameterType.PARAMETER_STRING,
                description=(
                    "Directory containing teleop_ros2 configs/ and assets/. "
                    "Leave empty to use the installed or source example root."
                ),
            ),
        )
        self.declare_parameter(
            "mcap_replay_path",
            "",
            ParameterDescriptor(
                type=ParameterType.PARAMETER_STRING,
                description=(
                    "Optional MCAP file to replay through TeleopSession instead "
                    "of connecting to live OpenXR/DeviceIO inputs."
                ),
            ),
        )

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
            "Leave empty to use the selected mode's default joint names. "
            "In modes that publish xr_teleop/finger_joints, provide ROS "
            "JointState name aliases matching the selected retargeter output count."
        )
        # A bare [] default is inferred by rclpy as BYTE_ARRAY on Humble.
        # Declare by type first, then initialize the unset default explicitly.
        left_finger_joint_names_param = self.declare_parameter(
            "left_finger_joint_names",
            Parameter.Type.STRING_ARRAY,
            ParameterDescriptor(
                type=ParameterType.PARAMETER_STRING_ARRAY,
                description=(
                    "Optional left-hand joint names for xr_teleop/finger_joints. "
                    "Empty means the selected mode's default names."
                ),
                additional_constraints=finger_joint_name_constraints,
            ),
        )
        right_finger_joint_names_param = self.declare_parameter(
            "right_finger_joint_names",
            Parameter.Type.STRING_ARRAY,
            ParameterDescriptor(
                type=ParameterType.PARAMETER_STRING_ARRAY,
                description=(
                    "Optional right-hand joint names for xr_teleop/finger_joints. "
                    "Empty means the selected mode's default names."
                ),
                additional_constraints=finger_joint_name_constraints,
            ),
        )
        _make_unset_string_array_parameter_empty(self, left_finger_joint_names_param)
        _make_unset_string_array_parameter_empty(self, right_finger_joint_names_param)

        rate_hz = self.get_parameter("rate_hz").get_parameter_value().double_value
        if rate_hz <= 0 or not math.isfinite(rate_hz):
            raise ValueError("Parameter 'rate_hz' must be > 0")
        self._sleep_period_s: float = 1.0 / rate_hz
        mode = self.get_parameter("mode").get_parameter_value().string_value
        if mode not in TELEOP_MODES:
            raise ValueError(
                f"Parameter 'mode' must be one of {TELEOP_MODES}, got {mode!r}"
            )
        self.get_logger().info(f"Mode: {mode}")
        self._mode: str = mode
        raw_hand_retargeter = (
            self.get_parameter("hand_retargeter").get_parameter_value().string_value
        )
        try:
            self._hand_retargeter: HandRetargeter = HandRetargeter(raw_hand_retargeter)
        except ValueError as exc:
            raise ValueError(
                f"Parameter 'hand_retargeter' must be one of {HAND_RETARGETERS}, "
                f"got {raw_hand_retargeter!r}"
            ) from exc
        self._resolved_hand_retargeter: HandRetargeter = resolve_hand_retargeter(
            self._mode, self._hand_retargeter
        )
        self._controller_uses_hands_source: bool = uses_hands_source_for_controller(
            self._mode, self._resolved_hand_retargeter
        )
        if self._mode in ("hand_teleop", "controller_teleop"):
            self.get_logger().info(f"Hand retargeter: {self._resolved_hand_retargeter}")
        if self._controller_uses_hands_source:
            self.get_logger().info(
                "Applying MANUS controller-to-hand transform after pose transform."
            )
        self._config_asset_root: Path = resolve_config_asset_root(
            self.get_parameter("config_asset_root").get_parameter_value().string_value,
            Path(__file__).resolve().parents[1],
        )
        self.get_logger().info(f"Config/asset root: {self._config_asset_root}")
        mcap_replay_path = (
            self.get_parameter("mcap_replay_path")
            .get_parameter_value()
            .string_value.strip()
        )
        self._session_mode: SessionMode = SessionMode.LIVE
        self._mcap_config: McapReplayConfig | None = None
        if mcap_replay_path:
            replay_path = Path(mcap_replay_path).expanduser().resolve()
            if not replay_path.is_file():
                raise FileNotFoundError(
                    f"mcap_replay_path file not found: {replay_path}"
                )
            self._session_mode = SessionMode.REPLAY
            self._mcap_config = McapReplayConfig(str(replay_path))
            self.get_logger().info(f"Replaying MCAP input: {replay_path}")

        self._pedal_collection_id: str = (
            self.get_parameter("pedal_collection_id").get_parameter_value().string_value
        )
        if not self._pedal_collection_id:
            raise ValueError("Parameter 'pedal_collection_id' must not be empty")

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

        self._left_finger_joint_name_aliases = _resolve_finger_joint_name_aliases(
            "left_finger_joint_names",
            self.get_parameter("left_finger_joint_names").value,
        )
        self._right_finger_joint_name_aliases = _resolve_finger_joint_name_aliases(
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

        self._config = build_session_config(
            self._mode,
            TeleopRos2SessionConfigContext(
                config_asset_root=self._config_asset_root,
                left_finger_joint_name_aliases=self._left_finger_joint_name_aliases,
                mcap_config=self._mcap_config,
                pedal_collection_id=self._pedal_collection_id,
                resolved_hand_retargeter=self._resolved_hand_retargeter,
                right_finger_joint_name_aliases=self._right_finger_joint_name_aliases,
                session_mode=self._session_mode,
            ),
        )

    def _build_wrist_tfs(
        self,
        ee_msg: PoseArray,
        *,
        right_available: bool,
        left_available: bool,
        now,
    ) -> List[TransformStamped]:
        """Build wrist TF transforms from a pre-built ee_poses PoseArray (left pose at index 0, right at index 1)."""
        tfs = []

        def _get_orientation(pose: Pose) -> List[float]:
            return [
                pose.orientation.x,
                pose.orientation.y,
                pose.orientation.z,
                pose.orientation.w,
            ]

        if left_available:
            pose = ee_msg.poses[0]
            tfs.append(
                make_transform(
                    now,
                    self._world_frame,
                    self._left_wrist_frame,
                    [pose.position.x, pose.position.y, pose.position.z],
                    _get_orientation(pose),
                )
            )
        if right_available:
            pose = ee_msg.poses[1]
            tfs.append(
                make_transform(
                    now,
                    self._world_frame,
                    self._right_wrist_frame,
                    [pose.position.x, pose.position.y, pose.position.z],
                    _get_orientation(pose),
                )
            )
        return tfs

    def _publish_controller_outputs(self, result: dict, now) -> None:
        left_ctrl = result["controller_left"]
        right_ctrl = result["controller_right"]
        ee_msg = build_ee_msg_from_controllers(
            left_ctrl,
            right_ctrl,
            now,
            self._world_frame,
            self._transform_rot,
            self._transform_trans,
            self._controller_uses_hands_source,
        )
        if ee_msg.poses:
            self._pub_ee_pose.publish(ee_msg)
        wrist_tfs = self._build_wrist_tfs(
            ee_msg,
            right_available=controller_aim_is_valid(right_ctrl),
            left_available=controller_aim_is_valid(left_ctrl),
            now=now,
        )
        if wrist_tfs:
            self._tf_broadcaster.sendTransform(wrist_tfs)
        if self._controller_uses_hands_source:
            hand_msg = build_hand_msg_from_hands(
                result["hand_left"],
                result["hand_right"],
                now,
                self._world_frame,
                self._transform_rot,
                self._transform_trans,
            )
            if hand_msg.poses:
                self._pub_hand.publish(hand_msg)

    def _publish_controller_payload(self, result: dict) -> None:
        if self._mode not in ("controller_raw", "controller_teleop", "full_body"):
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
        if self._mode not in ("controller_teleop", "hand_teleop"):
            return

        finger_joints_msg = build_finger_joints_msg(
            result["finger_joints_left"],
            result["finger_joints_right"],
            now,
            self._world_frame,
        )
        if finger_joints_msg is not None:
            self._pub_finger_joints.publish(finger_joints_msg)

    def _publish_full_body_payload(self, result: dict) -> None:
        if self._mode != "full_body":
            return

        full_body_data = result["full_body"]
        if full_body_data.is_none:
            return

        body_payload = build_full_body_payload(full_body_data)
        payload = msgpack.packb(body_payload, default=mnp.encode)
        body_msg = ByteMultiArray()
        body_msg.data = tuple(bytes([a]) for a in payload)
        self._pub_full_body.publish(body_msg)

    def _publish_hand_tracking_outputs(self, result: dict, now) -> None:
        left_hand = result["hand_left"]
        right_hand = result["hand_right"]
        hand_msg = build_hand_msg_from_hands(
            left_hand,
            right_hand,
            now,
            self._world_frame,
            self._transform_rot,
            self._transform_trans,
        )
        if hand_msg.poses:
            self._pub_hand.publish(hand_msg)

        ee_msg = build_ee_msg_from_hands(
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
            right_available=hand_wrist_is_valid(right_hand),
            left_available=hand_wrist_is_valid(left_hand),
            now=now,
        )
        if wrist_tfs:
            self._tf_broadcaster.sendTransform(wrist_tfs)

    def _publish_root_command(self, result: dict, now) -> None:
        if self._mode not in ("hand_teleop", "controller_teleop"):
            return

        root_command = result["root_command"]
        if root_command.is_none:
            return

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

    def run(self) -> int:
        while rclpy.ok():
            try:
                with TeleopSession(self._config) as session:
                    self.get_logger().info("TeleopSession started successfully")
                    while rclpy.ok():
                        result = session.step()

                        # Keep ROS time and other callbacks updated in this
                        # manual loop so stamped messages progress with /clock.
                        rclpy.spin_once(self, timeout_sec=0.0)

                        now = self.get_clock().now().to_msg()

                        if self._mode == "hand_teleop":
                            self._publish_hand_tracking_outputs(result, now)
                        elif self._mode == "controller_teleop":
                            self._publish_controller_outputs(result, now)

                        self._publish_root_command(result, now)
                        self._publish_finger_joints(result, now)
                        self._publish_controller_payload(result)
                        self._publish_full_body_payload(result)

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
