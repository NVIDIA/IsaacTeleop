# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Teleop DEVICEIO - Device I/O Module

This module provides trackers and teleop session functionality.

Tracker getters return TrackedT wrapper types containing `.data` (the raw data)
and `.timestamp` (DeviceOutputTimestamp with query/target times):
    HandTracker.get_left_hand(session) / get_right_hand(session) -> HandPoseTrackedT
    HeadTracker.get_head(session) -> HeadPoseTrackedT
    ControllerTracker.get_left_controller(session) / get_right_controller(session) -> ControllerSnapshotTrackedT
    FrameMetadataTrackerOak.get_data(session) -> FrameMetadataTrackedT
    FullBodyTrackerPico.get_body_pose(session) -> FullBodyPosePicoTrackedT

Import raw data types from isaacteleop.schema if you need to work with pose types.
"""

from ._deviceio import (
    ITracker,
    HandTracker,
    HeadTracker,
    ControllerTracker,
    FrameMetadataTrackerOak,
    FullBodyTrackerPico,
    DeviceIOSession,
    DeviceOutputTimestamp,
    HandPoseTrackedT,
    HeadPoseTrackedT,
    ControllerSnapshotTrackedT,
    FrameMetadataTrackedT,
    FullBodyPosePicoTrackedT,
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
    DeviceDataTimestamp,
    FrameMetadata,
)

__all__ = [
    "ControllerInputState",
    "ControllerPose",
    "ControllerSnapshot",
    "DeviceDataTimestamp",
    "DeviceOutputTimestamp",
    "FrameMetadata",
    "HandPoseTrackedT",
    "HeadPoseTrackedT",
    "ControllerSnapshotTrackedT",
    "FrameMetadataTrackedT",
    "FullBodyPosePicoTrackedT",
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
