# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Teleop DEVICEIO - Device I/O Module

This module provides trackers and teleop session functionality.

Note: HeadTracker.get_head(session) returns HeadPoseT from isaacteleop.schema.
    HandTracker.get_left_hand(session) / get_right_hand(session) return HandPoseT from isaacteleop.schema.
    ControllerTracker.get_controller_data(session) returns ControllerSnapshot from isaacteleop.schema.
    FrameMetadataTrackerOak.get_data(session) returns OakMetadata from isaacteleop.schema.
Import these types from isaacteleop.schema if you need to work with pose types.
"""

from ._deviceio import (
    ITracker,
    HandTracker,
    HeadTracker,
    ControllerTracker,
    FrameMetadataTrackerOak,
    FullBodyTrackerPico,
    DeviceIOSession,
    NUM_JOINTS,
    JOINT_PALM,
    JOINT_WRIST,
    JOINT_THUMB_TIP,
    JOINT_INDEX_TIP,
)

# Import OpenXRSessionHandles from oxr module to avoid double registration
from ..oxr import OpenXRSessionHandles

# Import controller and camera types from schema module (where they are now defined)
from ..schema import (
    ControllerInputState,
    ControllerPose,
    ControllerSnapshot,
    StreamType,
    FrameMetadata,
    OakMetadata,
    Timestamp,
)

__all__ = [
    "ControllerInputState",
    "ControllerPose",
    "ControllerSnapshot",
    "StreamType",
    "FrameMetadata",
    "OakMetadata",
    "Timestamp",
    "ITracker",
    "HandTracker",
    "HeadTracker",
    "ControllerTracker",
    "FrameMetadataTrackerOak",
    "FullBodyTrackerPico",
    "OpenXRSessionHandles",
    "DeviceIOSession",
    "NUM_JOINTS",
    "JOINT_PALM",
    "JOINT_WRIST",
    "JOINT_THUMB_TIP",
    "JOINT_INDEX_TIP",
]
