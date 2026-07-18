# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES.
# All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Tests for tensor-group to ROS-message conversion."""

import numpy as np
from builtin_interfaces.msg import Time

from isaacteleop.retargeting_engine.interface import OptionalTensorGroup, TensorGroup
from isaacteleop.retargeting_engine.tensor_types import (
    NUM_HAND_JOINTS,
    ControllerInput,
    ControllerInputIndex,
    HandInput,
    HandInputIndex,
)

from constants import HAND_POSE_NAMES
from messages import (
    build_controller_payload,
    build_ee_msg_from_controllers,
    build_hand_msg,
)


def _active_controller() -> TensorGroup:
    controller = TensorGroup(ControllerInput())
    controller[ControllerInputIndex.GRIP_POSITION] = np.array(
        [1.0, 2.0, 3.0], dtype=np.float32
    )
    controller[ControllerInputIndex.GRIP_ORIENTATION] = np.array(
        [0.0, 0.0, 0.0, 1.0], dtype=np.float32
    )
    controller[ControllerInputIndex.GRIP_IS_VALID] = True
    controller[ControllerInputIndex.AIM_POSITION] = np.array(
        [4.0, 5.0, 6.0], dtype=np.float32
    )
    controller[ControllerInputIndex.AIM_ORIENTATION] = np.array(
        [0.0, 0.0, 0.0, 1.0], dtype=np.float32
    )
    controller[ControllerInputIndex.AIM_IS_VALID] = True
    controller[ControllerInputIndex.PRIMARY_CLICK] = 1.0
    controller[ControllerInputIndex.SECONDARY_CLICK] = 0.0
    controller[ControllerInputIndex.THUMBSTICK_CLICK] = 1.0
    controller[ControllerInputIndex.MENU_CLICK] = 0.0
    controller[ControllerInputIndex.THUMBSTICK_X] = 0.25
    controller[ControllerInputIndex.THUMBSTICK_Y] = -0.5
    controller[ControllerInputIndex.SQUEEZE_VALUE] = 0.75
    controller[ControllerInputIndex.TRIGGER_VALUE] = 0.5
    return controller


def _active_hand() -> TensorGroup:
    hand = TensorGroup(HandInput())
    positions = np.zeros((NUM_HAND_JOINTS, 3), dtype=np.float32)
    positions[:, 0] = np.arange(NUM_HAND_JOINTS, dtype=np.float32)
    orientations = np.zeros((NUM_HAND_JOINTS, 4), dtype=np.float32)
    orientations[:, 3] = 1.0
    valid = np.ones(NUM_HAND_JOINTS, dtype=np.uint8)

    hand[HandInputIndex.JOINT_POSITIONS] = positions
    hand[HandInputIndex.JOINT_ORIENTATIONS] = orientations
    hand[HandInputIndex.JOINT_RADII] = np.ones(NUM_HAND_JOINTS, dtype=np.float32)
    hand[HandInputIndex.JOINT_VALID] = valid
    return hand


def test_ee_message_has_fixed_entries_and_invalid_placeholder() -> None:
    left = _active_controller()
    right = OptionalTensorGroup(ControllerInput())

    msg = build_ee_msg_from_controllers(left, right, Time(), "world")

    assert list(msg.name) == ["left", "right"]
    assert list(msg.is_valid) == [True, False]
    assert msg.pose[0].position.x == 4.0
    assert msg.pose[1].position.x == 0.0
    assert msg.pose[1].orientation.w == 1.0


def test_hand_message_has_stable_names_and_absent_side_placeholders() -> None:
    left = _active_hand()
    right = OptionalTensorGroup(HandInput())

    msg = build_hand_msg(left, right, Time(), "world")

    expected_names = [
        f"{side}_{name}" for side in ("left", "right") for name in HAND_POSE_NAMES
    ]
    assert list(msg.name) == expected_names
    assert len(msg.pose) == len(expected_names)
    assert all(msg.is_valid[: len(HAND_POSE_NAMES)])
    assert not any(msg.is_valid[len(HAND_POSE_NAMES) :])
    assert "left_PALM" not in msg.name


def test_controller_payload_schema_and_absent_side_defaults() -> None:
    payload = build_controller_payload(
        _active_controller(), OptionalTensorGroup(ControllerInput())
    )

    assert set(payload) == {
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
    assert isinstance(payload["timestamp"], int)
    assert payload["left_is_active"] is True
    assert payload["right_is_active"] is False
    assert payload["left_thumbstick"] == [0.25, -0.5]
    assert payload["right_aim_position"] == [0.0, 0.0, 0.0]
    assert payload["right_aim_orientation"] == [0.0, 0.0, 0.0, 1.0]
