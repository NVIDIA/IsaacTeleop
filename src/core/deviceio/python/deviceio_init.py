# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""TeleopCore DEVICEIO - Device I/O Module

This module provides trackers and teleop session functionality.

Note: HeadTracker.get_head(session) returns HeadPoseT from teleopcore.schema.
    HandTracker.get_left_hand(session) / get_right_hand(session) return HandPoseT from teleopcore.schema.
    ControllerTracker.get_controller_data(session) returns ControllerSnapshot from teleopcore.schema.
Import these types from teleopcore.schema if you need to work with pose types.
"""

from ._deviceio import (
    ITracker,
    HandTracker,
    HeadTracker,
    ControllerTracker,
    DeviceIOSession,
    NUM_JOINTS,
    JOINT_PALM,
    JOINT_WRIST,
    JOINT_THUMB_TIP,
    JOINT_INDEX_TIP,
)

# Import OpenXRSessionHandles from oxr module to avoid double registration
from ..oxr import OpenXRSessionHandles

# Import controller types from schema module (where they are now defined)
from ..schema import (
    ControllerInputState,
    ControllerPose,
    ControllerSnapshot,
    Timestamp,
)

__all__ = [
    "ControllerInputState",
    "ControllerPose",
    "ControllerSnapshot",
    "Timestamp",
    "ITracker",
    "HandTracker",
    "HeadTracker",
    "ControllerTracker",
    "OpenXRSessionHandles",
    "DeviceIOSession",
    "NUM_JOINTS",
    "JOINT_PALM",
    "JOINT_WRIST",
    "JOINT_THUMB_TIP",
    "JOINT_INDEX_TIP",
]

