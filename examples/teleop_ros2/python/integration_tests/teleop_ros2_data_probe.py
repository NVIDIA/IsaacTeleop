#!/usr/bin/env python3
# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Subscribe to the teleop ROS 2 topics and validate published message data."""

from __future__ import annotations

import argparse
import math
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import msgpack
import msgpack_numpy as mnp
import rclpy
from geometry_msgs.msg import Pose, PoseArray, PoseStamped, TwistStamped
from sensor_msgs.msg import JointState
from std_msgs.msg import ByteMultiArray


_CONTROLLER_PAYLOAD_KEYS = {
    "timestamp",
    "left_thumbstick",
    "right_thumbstick",
    "left_trigger_value",
    "right_trigger_value",
    "left_squeeze_value",
    "right_squeeze_value",
    "left_aim_position",
    "right_aim_position",
    "left_grip_position",
    "right_grip_position",
    "left_aim_orientation",
    "right_aim_orientation",
    "left_grip_orientation",
    "right_grip_orientation",
    "left_primary_click",
    "right_primary_click",
    "left_secondary_click",
    "right_secondary_click",
    "left_thumbstick_click",
    "right_thumbstick_click",
    "left_menu_click",
    "right_menu_click",
    "left_is_active",
    "right_is_active",
}
_FULL_BODY_JOINT_COUNT = 24
_HAND_POSE_COUNT = 48
_SHARPA_JOINT_COUNT_PER_HAND = 22
_TRIHAND_JOINT_COUNT_PER_HAND = 7


@dataclass(frozen=True)
class _TopicProbe:
    message_type: type
    required: bool
    validate: Callable[[Any], None]


# Validation helpers


def _decode_byte_multi_array(msg: ByteMultiArray) -> Any:
    payload = bytearray()
    for item in msg.data:
        if isinstance(item, (bytes, bytearray)):
            payload.extend(item)
        else:
            payload.append(int(item) & 0xFF)
    if not payload:
        raise ValueError("payload is empty")
    return msgpack.unpackb(bytes(payload), object_hook=mnp.decode, raw=False)


def _expect_finite(value: float, label: str) -> None:
    if not math.isfinite(float(value)):
        raise ValueError(f"{label} must be finite, got {value!r}")


def _expect_numeric_sequence(
    values: Sequence[Any], expected_len: int, label: str
) -> None:
    if len(values) != expected_len:
        raise ValueError(f"{label} must have {expected_len} entries, got {len(values)}")
    for index, value in enumerate(values):
        _expect_finite(float(value), f"{label}[{index}]")


def _expect_quaternion(values: Sequence[Any], label: str) -> None:
    _expect_numeric_sequence(values, 4, label)
    norm = math.sqrt(sum(float(value) * float(value) for value in values))
    if norm <= 1e-6:
        raise ValueError(f"{label} must be a non-zero quaternion")


def _expect_timestamp(value: Any, label: str) -> None:
    if not isinstance(value, int):
        raise ValueError(f"{label} must be an integer, got {type(value).__name__}")
    if value <= 0:
        raise ValueError(f"{label} must be positive, got {value}")


def _validate_controller_data(msg: ByteMultiArray) -> None:
    payload = _decode_byte_multi_array(msg)
    if not isinstance(payload, Mapping):
        raise ValueError(f"payload must be a mapping, got {type(payload).__name__}")

    missing = sorted(_CONTROLLER_PAYLOAD_KEYS - set(payload))
    if missing:
        raise ValueError(f"payload is missing keys: {missing}")

    _expect_timestamp(payload["timestamp"], "timestamp")
    if not isinstance(payload["left_is_active"], bool):
        raise ValueError("left_is_active must be a bool")
    if not isinstance(payload["right_is_active"], bool):
        raise ValueError("right_is_active must be a bool")
    if not (payload["left_is_active"] or payload["right_is_active"]):
        raise ValueError("at least one controller must be active")

    for key in ("left_thumbstick", "right_thumbstick"):
        _expect_numeric_sequence(payload[key], 2, key)
    for key in (
        "left_aim_position",
        "right_aim_position",
        "left_grip_position",
        "right_grip_position",
    ):
        _expect_numeric_sequence(payload[key], 3, key)
    for key in (
        "left_aim_orientation",
        "right_aim_orientation",
        "left_grip_orientation",
        "right_grip_orientation",
    ):
        _expect_quaternion(payload[key], key)
    for key in (
        "left_trigger_value",
        "right_trigger_value",
        "left_squeeze_value",
        "right_squeeze_value",
        "left_primary_click",
        "right_primary_click",
        "left_secondary_click",
        "right_secondary_click",
        "left_thumbstick_click",
        "right_thumbstick_click",
        "left_menu_click",
        "right_menu_click",
    ):
        _expect_finite(float(payload[key]), key)


def _validate_ee_poses(msg: PoseArray) -> None:
    _validate_pose_array(msg, expected_count=2, label="ee_poses")


def _validate_full_body(msg: ByteMultiArray) -> None:
    payload = _decode_byte_multi_array(msg)
    if not isinstance(payload, Mapping):
        raise ValueError(f"payload must be a mapping, got {type(payload).__name__}")
    for key in (
        "timestamp",
        "joint_names",
        "joint_positions",
        "joint_orientations",
        "joint_valid",
    ):
        if key not in payload:
            raise ValueError(f"payload is missing key: {key}")

    _expect_timestamp(payload["timestamp"], "timestamp")
    names = payload["joint_names"]
    positions = payload["joint_positions"]
    orientations = payload["joint_orientations"]
    valid = payload["joint_valid"]
    if len(names) != _FULL_BODY_JOINT_COUNT:
        raise ValueError(
            f"joint_names must have {_FULL_BODY_JOINT_COUNT} entries, got {len(names)}"
        )
    if len(positions) != len(names):
        raise ValueError("joint_positions length must match joint_names")
    if len(orientations) != len(names):
        raise ValueError("joint_orientations length must match joint_names")
    if len(valid) != len(names):
        raise ValueError("joint_valid length must match joint_names")

    for index, name in enumerate(names):
        if not isinstance(name, str) or not name:
            raise ValueError(f"joint_names[{index}] must be a non-empty string")
        if not isinstance(valid[index], bool):
            raise ValueError(f"joint_valid[{index}] must be a bool")
        _expect_numeric_sequence(positions[index], 3, f"joint_positions[{index}]")
        _expect_numeric_sequence(orientations[index], 4, f"joint_orientations[{index}]")
        if valid[index]:
            _expect_quaternion(orientations[index], f"joint_orientations[{index}]")


def _validate_hand_poses(msg: PoseArray) -> None:
    _validate_pose_array(msg, expected_count=_HAND_POSE_COUNT, label="hand")


def _validate_header_frame(frame_id: str, label: str) -> None:
    if not frame_id:
        raise ValueError(f"{label}.header.frame_id must be non-empty")


def _validate_joint_state(msg: JointState, expected_count: int) -> None:
    _validate_header_frame(msg.header.frame_id, "finger_joints")
    if len(msg.name) != expected_count:
        raise ValueError(
            f"finger_joints.name must have {expected_count} entries, got {len(msg.name)}"
        )
    if len(msg.position) != expected_count:
        raise ValueError(
            "finger_joints.position must have the same expected length as name, "
            f"got {len(msg.position)}"
        )
    if len(set(msg.name)) != len(msg.name):
        raise ValueError("finger_joints.name entries must be unique")
    for index, name in enumerate(msg.name):
        if not name:
            raise ValueError(f"finger_joints.name[{index}] must be non-empty")
        _expect_finite(msg.position[index], f"finger_joints.position[{index}]")


def _validate_pose(pose: Pose, label: str) -> None:
    _expect_finite(pose.position.x, f"{label}.position.x")
    _expect_finite(pose.position.y, f"{label}.position.y")
    _expect_finite(pose.position.z, f"{label}.position.z")
    _expect_quaternion(
        [
            pose.orientation.x,
            pose.orientation.y,
            pose.orientation.z,
            pose.orientation.w,
        ],
        f"{label}.orientation",
    )


def _validate_pose_array(msg: PoseArray, *, expected_count: int, label: str) -> None:
    _validate_header_frame(msg.header.frame_id, label)
    if len(msg.poses) != expected_count:
        raise ValueError(
            f"{label}.poses must have {expected_count} entries, got {len(msg.poses)}"
        )
    for index, pose in enumerate(msg.poses):
        _validate_pose(pose, f"{label}.poses[{index}]")


def _validate_pose_stamped(msg: PoseStamped) -> None:
    _validate_header_frame(msg.header.frame_id, "root_pose")
    _validate_pose(msg.pose, "root_pose.pose")


def _validate_twist_stamped(msg: TwistStamped) -> None:
    _validate_header_frame(msg.header.frame_id, "root_twist")
    for field, value in (
        ("linear.x", msg.twist.linear.x),
        ("linear.y", msg.twist.linear.y),
        ("linear.z", msg.twist.linear.z),
        ("angular.x", msg.twist.angular.x),
        ("angular.y", msg.twist.angular.y),
        ("angular.z", msg.twist.angular.z),
    ):
        _expect_finite(value, f"root_twist.twist.{field}")


# Mode helpers


def _expected_finger_joint_count(mode: str, hand_retargeter: str) -> int:
    resolved = _resolve_hand_retargeter(mode, hand_retargeter)
    if resolved == "trihand":
        return _TRIHAND_JOINT_COUNT_PER_HAND * 2
    if resolved in ("dexpilot", "pink_ik"):
        return _SHARPA_JOINT_COUNT_PER_HAND * 2
    raise ValueError(
        f"Unsupported hand_retargeter {hand_retargeter!r} for mode {mode!r}"
    )


def _resolve_hand_retargeter(mode: str, hand_retargeter: str) -> str:
    if hand_retargeter == "mode_default":
        if mode == "controller_teleop":
            return "trihand"
        if mode == "hand_teleop":
            return "dexpilot"
    return hand_retargeter


# Probe builders


def _controller_data_probe(*, required: bool = False) -> _TopicProbe:
    return _TopicProbe(
        ByteMultiArray, required=required, validate=_validate_controller_data
    )


def _ee_pose_probe(*, required: bool = True) -> _TopicProbe:
    return _TopicProbe(PoseArray, required=required, validate=_validate_ee_poses)


def _finger_joint_probe(
    mode: str, hand_retargeter: str, *, required: bool = True
) -> _TopicProbe:
    return _TopicProbe(
        JointState,
        required=required,
        validate=lambda msg: _validate_joint_state(
            msg, _expected_finger_joint_count(mode, hand_retargeter)
        ),
    )


def _full_body_probe(*, required: bool = False) -> _TopicProbe:
    return _TopicProbe(ByteMultiArray, required=required, validate=_validate_full_body)


def _hand_pose_probe(*, required: bool = True) -> _TopicProbe:
    return _TopicProbe(PoseArray, required=required, validate=_validate_hand_poses)


def _root_pose_probe(*, required: bool = False) -> _TopicProbe:
    return _TopicProbe(PoseStamped, required=required, validate=_validate_pose_stamped)


def _root_twist_probe(*, required: bool = False) -> _TopicProbe:
    return _TopicProbe(
        TwistStamped, required=required, validate=_validate_twist_stamped
    )


# Topic policy


def _topic_probes(mode: str, hand_retargeter: str) -> dict[str, _TopicProbe]:
    optional = {
        "xr_teleop/root_twist": _root_twist_probe(),
        "xr_teleop/root_pose": _root_pose_probe(),
    }
    if mode == "controller_raw":
        return {
            "xr_teleop/controller_data": _controller_data_probe(),
        }
    if mode == "controller_teleop":
        probes = {
            # The CI CloudXR runtime can expose head/hand devices without active
            # controllers. In that state controller_teleop may reach startup
            # without publishing controller-backed samples, so validate samples
            # when present but do not use them as required liveness signals.
            "xr_teleop/controller_data": _controller_data_probe(),
            "xr_teleop/ee_poses": _ee_pose_probe(required=False),
            "xr_teleop/finger_joints": _finger_joint_probe(
                mode, hand_retargeter, required=False
            ),
            **optional,
        }
        if _resolve_hand_retargeter(mode, hand_retargeter) in ("dexpilot", "pink_ik"):
            probes["xr_teleop/hand"] = _hand_pose_probe(required=False)
        return probes
    if mode == "hand_teleop":
        return {
            "xr_teleop/hand": _hand_pose_probe(),
            "xr_teleop/ee_poses": _ee_pose_probe(),
            "xr_teleop/finger_joints": _finger_joint_probe(mode, hand_retargeter),
            **optional,
        }
    if mode == "full_body":
        return {
            "xr_teleop/controller_data": _controller_data_probe(),
            "xr_teleop/full_body": _full_body_probe(),
        }
    raise ValueError(f"Unsupported mode {mode!r}")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Validate data published by examples/teleop_ros2."
    )
    parser.add_argument(
        "--mode",
        choices=("controller_teleop", "hand_teleop", "controller_raw", "full_body"),
        required=True,
        help="teleop_ros2_node mode being probed.",
    )
    parser.add_argument(
        "--hand-retargeter",
        choices=("mode_default", "trihand", "pink_ik", "dexpilot"),
        default="mode_default",
        help="hand_retargeter parameter value used by the publisher.",
    )
    parser.add_argument(
        "--timeout-sec",
        default=20.0,
        type=float,
        help="Maximum time to wait for required valid samples.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    probes = _topic_probes(args.mode, args.hand_retargeter)
    valid_topics: set[str] = set()
    invalid_samples: list[str] = []

    rclpy.init()
    node = rclpy.create_node(f"teleop_ros2_data_probe_{args.mode}")
    try:
        subscriptions = []
        for topic, probe in probes.items():

            def _callback(msg, *, topic=topic, probe=probe):
                try:
                    probe.validate(msg)
                except Exception as exc:  # noqa: BLE001 - surface validator context.
                    invalid_samples.append(f"{topic}: {exc}")
                    return
                valid_topics.add(topic)

            subscriptions.append(
                node.create_subscription(probe.message_type, topic, _callback, 10)
            )

        required_topics = {topic for topic, probe in probes.items() if probe.required}
        deadline = time.monotonic() + args.timeout_sec
        while time.monotonic() < deadline:
            rclpy.spin_once(node, timeout_sec=0.1)
            if required_topics and required_topics <= valid_topics:
                break

        missing_topics = sorted(required_topics - valid_topics)
        if invalid_samples:
            print("Invalid teleop ROS2 samples observed:")
            for sample in invalid_samples:
                print(f"  - {sample}")
            return 1
        if missing_topics:
            print(
                f"Timed out after {args.timeout_sec:.1f}s waiting for valid samples "
                f"on required topics: {missing_topics}"
            )
            print(f"Validated topics before timeout: {sorted(valid_topics)}")
            return 1

        print(
            f"Validated teleop ROS2 data for mode {args.mode}: "
            f"{sorted(required_topics)}"
        )
        return 0
    finally:
        node.destroy_node()
        rclpy.shutdown()


if __name__ == "__main__":
    raise SystemExit(main())
