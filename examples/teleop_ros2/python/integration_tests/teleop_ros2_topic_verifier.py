#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Verify teleop_ros2_node.py publishes expected topics for one mode."""

from __future__ import annotations

import argparse
import math
import sys
import time
from typing import Callable

import msgpack
import rclpy
from geometry_msgs.msg import PoseArray, PoseStamped, TwistStamped
from rclpy.node import Node
from sensor_msgs.msg import JointState
from std_msgs.msg import ByteMultiArray
from tf2_msgs.msg import TFMessage


_MODES = ("controller_teleop", "hand_teleop", "controller_raw", "full_body")
_EXPECTED_TF_FRAMES = {"right_wrist", "left_wrist", "head"}


def _is_finite_sequence(values) -> bool:
    return all(math.isfinite(float(value)) for value in values)


def _byte_multi_array_to_bytes(msg: ByteMultiArray) -> bytes:
    payload = bytearray()
    for value in msg.data:
        if isinstance(value, bytes):
            payload.extend(value)
        else:
            payload.append((int(value) + 256) % 256)
    return bytes(payload)


def _unpack_msgpack(msg: ByteMultiArray) -> dict:
    return msgpack.unpackb(
        _byte_multi_array_to_bytes(msg), raw=False, strict_map_key=False
    )


def _assert_pose_array(msg: PoseArray, *, expected_count: int) -> None:
    if msg.header.frame_id != "world":
        raise ValueError(f"unexpected frame_id {msg.header.frame_id!r}")
    if len(msg.poses) != expected_count:
        raise ValueError(f"expected {expected_count} poses, got {len(msg.poses)}")
    positions = []
    for pose in msg.poses:
        position = (pose.position.x, pose.position.y, pose.position.z)
        orientation = (
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        )
        if not _is_finite_sequence(position):
            raise ValueError("pose position contains non-finite values")
        if not _is_finite_sequence(orientation):
            raise ValueError("pose orientation contains non-finite values")
        positions.extend(position)
    if not any(abs(value) > 1e-6 for value in positions):
        raise ValueError("pose array positions are all zero")


def _assert_pose_stamped(
    msg: PoseStamped, *, require_nonzero_position: bool = False
) -> None:
    if msg.header.frame_id != "world":
        raise ValueError(f"unexpected frame_id {msg.header.frame_id!r}")
    position = (msg.pose.position.x, msg.pose.position.y, msg.pose.position.z)
    orientation = (
        msg.pose.orientation.x,
        msg.pose.orientation.y,
        msg.pose.orientation.z,
        msg.pose.orientation.w,
    )
    if not _is_finite_sequence(position):
        raise ValueError("PoseStamped position contains non-finite values")
    if not _is_finite_sequence(orientation):
        raise ValueError("PoseStamped orientation contains non-finite values")
    if require_nonzero_position and not any(abs(value) > 1e-6 for value in position):
        raise ValueError("PoseStamped position is all zero")


def _assert_joint_state(msg: JointState) -> None:
    if msg.header.frame_id != "world":
        raise ValueError(f"unexpected frame_id {msg.header.frame_id!r}")
    if not msg.name:
        raise ValueError("JointState names are empty")
    if len(msg.position) != len(msg.name):
        raise ValueError("JointState names and positions differ in length")
    if not _is_finite_sequence(msg.position):
        raise ValueError("JointState positions contain non-finite values")


def _assert_twist(msg: TwistStamped) -> None:
    if msg.header.frame_id != "world":
        raise ValueError(f"unexpected frame_id {msg.header.frame_id!r}")
    values = (
        msg.twist.linear.x,
        msg.twist.linear.y,
        msg.twist.linear.z,
        msg.twist.angular.x,
        msg.twist.angular.y,
        msg.twist.angular.z,
    )
    if not _is_finite_sequence(values):
        raise ValueError("TwistStamped contains non-finite values")


def _assert_controller_payload(msg: ByteMultiArray) -> None:
    payload = _unpack_msgpack(msg)
    for side in ("left", "right"):
        if payload[f"{side}_is_active"] is not True:
            raise ValueError(f"{side} controller is not active")
        for field in ("aim_position", "grip_position"):
            values = payload[f"{side}_{field}"]
            if len(values) != 3:
                raise ValueError(f"{side}_{field} must have 3 values")
            if not _is_finite_sequence(values):
                raise ValueError(f"{side}_{field} contains non-finite values")
            if not any(abs(float(value)) > 1e-6 for value in values):
                raise ValueError(f"{side}_{field} is all zero")
        for field in ("aim_orientation", "grip_orientation"):
            values = payload[f"{side}_{field}"]
            if len(values) != 4:
                raise ValueError(f"{side}_{field} must have 4 values")
            if not _is_finite_sequence(values):
                raise ValueError(f"{side}_{field} contains non-finite values")
        thumbstick = payload[f"{side}_thumbstick"]
        if len(thumbstick) != 2:
            raise ValueError(f"{side}_thumbstick must have 2 values")
        if not _is_finite_sequence(thumbstick):
            raise ValueError(f"{side}_thumbstick contains non-finite values")
        if not 0.0 <= float(payload[f"{side}_trigger_value"]) <= 1.0:
            raise ValueError(f"{side}_trigger_value must be in [0, 1]")
        if not 0.0 <= float(payload[f"{side}_squeeze_value"]) <= 1.0:
            raise ValueError(f"{side}_squeeze_value must be in [0, 1]")


def _assert_full_body_payload(msg: ByteMultiArray) -> None:
    payload = _unpack_msgpack(msg)
    if len(payload["joint_names"]) != 24:
        raise ValueError("expected 24 full-body joint names")
    if len(payload["joint_positions"]) != 24:
        raise ValueError("expected 24 full-body joint positions")
    if len(payload["joint_orientations"]) != 24:
        raise ValueError("expected 24 full-body joint orientations")
    if len(payload["joint_valid"]) != 24:
        raise ValueError("expected 24 full-body joint valid flags")
    if not any(bool(value) for value in payload["joint_valid"]):
        raise ValueError("all full-body joints are invalid")
    for values in payload["joint_positions"]:
        if len(values) != 3:
            raise ValueError("full-body joint position must have 3 values")
        if not _is_finite_sequence(values):
            raise ValueError("full-body joint position contains non-finite values")
    for values in payload["joint_orientations"]:
        if len(values) != 4:
            raise ValueError("full-body joint orientation must have 4 values")
        if not _is_finite_sequence(values):
            raise ValueError("full-body joint orientation contains non-finite values")


class TopicVerifier(Node):
    """Small ROS 2 node that waits for mode-specific verified messages."""

    def __init__(self, mode: str) -> None:
        super().__init__("teleop_ros2_topic_verifier")
        self._pending: set[str] = set()
        self._errors: dict[str, str] = {}
        self._seen_tf_frames: set[str] = set()

        for name, topic, msg_type, validator in self._expected_subscriptions(mode):
            self._pending.add(name)
            self.create_subscription(
                msg_type, topic, self._make_callback(name, validator), 10
            )

        if mode in ("controller_teleop", "hand_teleop"):
            self._pending.add("tf")
            self.create_subscription(TFMessage, "/tf", self._tf_callback, 100)

    @property
    def pending(self) -> set[str]:
        return set(self._pending)

    @property
    def errors(self) -> dict[str, str]:
        return dict(self._errors)

    def _make_callback(self, name: str, validator: Callable) -> Callable:
        def _callback(msg) -> None:
            if name not in self._pending:
                return
            try:
                validator(msg)
            except ValueError as exc:
                self._errors[name] = str(exc)
                return
            self._errors.pop(name, None)
            self._pending.discard(name)

        return _callback

    def _tf_callback(self, msg: TFMessage) -> None:
        if "tf" not in self._pending:
            return
        for transform in msg.transforms:
            if transform.header.frame_id == "world":
                self._seen_tf_frames.add(transform.child_frame_id)
        missing = _EXPECTED_TF_FRAMES - self._seen_tf_frames
        if missing:
            self._errors["tf"] = f"missing TF frames: {sorted(missing)}"
            return
        self._errors.pop("tf", None)
        self._pending.discard("tf")

    def _expected_subscriptions(
        self, mode: str
    ) -> list[tuple[str, str, type, Callable]]:
        if mode == "controller_teleop":
            return [
                (
                    "ee_pose_left",
                    "xr_teleop/ee_pose_left",
                    PoseStamped,
                    lambda msg: _assert_pose_stamped(
                        msg, require_nonzero_position=True
                    ),
                ),
                (
                    "ee_pose_right",
                    "xr_teleop/ee_pose_right",
                    PoseStamped,
                    lambda msg: _assert_pose_stamped(
                        msg, require_nonzero_position=True
                    ),
                ),
                ("root_twist", "xr_teleop/root_twist", TwistStamped, _assert_twist),
                ("root_pose", "xr_teleop/root_pose", PoseStamped, _assert_pose_stamped),
                ("head_pose", "xr_teleop/head_pose", PoseStamped, _assert_pose_stamped),
                (
                    "finger_joints",
                    "xr_teleop/finger_joints",
                    JointState,
                    _assert_joint_state,
                ),
                (
                    "controller_data",
                    "xr_teleop/controller_data",
                    ByteMultiArray,
                    _assert_controller_payload,
                ),
            ]
        if mode == "hand_teleop":
            return [
                (
                    "hand",
                    "xr_teleop/hand",
                    PoseArray,
                    lambda msg: _assert_pose_array(msg, expected_count=50),
                ),
                (
                    "ee_pose_left",
                    "xr_teleop/ee_pose_left",
                    PoseStamped,
                    lambda msg: _assert_pose_stamped(
                        msg, require_nonzero_position=True
                    ),
                ),
                (
                    "ee_pose_right",
                    "xr_teleop/ee_pose_right",
                    PoseStamped,
                    lambda msg: _assert_pose_stamped(
                        msg, require_nonzero_position=True
                    ),
                ),
                ("root_twist", "xr_teleop/root_twist", TwistStamped, _assert_twist),
                ("root_pose", "xr_teleop/root_pose", PoseStamped, _assert_pose_stamped),
                ("head_pose", "xr_teleop/head_pose", PoseStamped, _assert_pose_stamped),
                (
                    "finger_joints",
                    "xr_teleop/finger_joints",
                    JointState,
                    _assert_joint_state,
                ),
            ]
        if mode == "controller_raw":
            return [
                (
                    "controller_data",
                    "xr_teleop/controller_data",
                    ByteMultiArray,
                    _assert_controller_payload,
                ),
            ]
        if mode == "full_body":
            return [
                (
                    "full_body",
                    "xr_teleop/full_body",
                    ByteMultiArray,
                    _assert_full_body_payload,
                ),
                (
                    "controller_data",
                    "xr_teleop/controller_data",
                    ByteMultiArray,
                    _assert_controller_payload,
                ),
            ]
        raise ValueError(f"Unsupported mode: {mode}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=_MODES, required=True)
    parser.add_argument("--timeout", type=float, default=20.0)
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    rclpy.init()
    verifier = TopicVerifier(args.mode)
    try:
        deadline = time.monotonic() + args.timeout
        while verifier.pending and time.monotonic() < deadline:
            rclpy.spin_once(verifier, timeout_sec=0.1)

        if verifier.pending:
            print(
                f"Timed out waiting for verified {args.mode} topics: {sorted(verifier.pending)}",
                file=sys.stderr,
            )
            for name, error in sorted(verifier.errors.items()):
                print(f"  {name}: {error}", file=sys.stderr)
            return 1

        print(f"Verified teleop_ros2 topics for mode {args.mode}")
        return 0
    finally:
        verifier.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
