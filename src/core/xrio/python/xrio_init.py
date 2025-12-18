# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""TeleopCore XRIO - Extended Reality I/O Module

This module provides trackers and teleop session functionality.

Note: HeadTracker.get_head() returns HeadPoseT from teleopcore.schema.
      HandTracker.get_left_hand() / get_right_hand() return HandPoseT from teleopcore.schema.
Import these types from teleopcore.schema if you need to work with pose types.
"""

from ._xrio import (
    Hand,
    ControllerInputState,
    ControllerPose,
    ControllerSnapshot,
    ITracker,
    HandTracker,
    HeadTracker,
    ControllerTracker,
    XrioSessionBuilder,
    XrioSession,
    NUM_JOINTS,
    JOINT_PALM,
    JOINT_WRIST,
    JOINT_THUMB_TIP,
    JOINT_INDEX_TIP,
)

# Import OpenXRSessionHandles from oxr module to avoid double registration
from ..oxr import OpenXRSessionHandles

__all__ = [
    "Hand",
    "ControllerInputState",
    "ControllerPose",
    "ControllerSnapshot",
    "ITracker",
    "HandTracker",
    "HeadTracker",
    "ControllerTracker",
    "OpenXRSessionHandles",
    "XrioSessionBuilder",
    "XrioSession",
    "NUM_JOINTS",
    "JOINT_PALM",
    "JOINT_WRIST",
    "JOINT_THUMB_TIP",
    "JOINT_INDEX_TIP",
]

