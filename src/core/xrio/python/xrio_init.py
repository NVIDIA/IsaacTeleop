# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""TeleopCore XRIO - Extended Reality I/O Module

This module provides trackers and teleop session functionality.
"""

from ._xrio import (
    JointPose,
    HandData,
    HeadPose,
    ITracker,
    HandTracker,
    HeadTracker,
    TeleopSessionBuilder,
    TeleopSession,
    NUM_JOINTS,
    JOINT_PALM,
    JOINT_WRIST,
    JOINT_THUMB_TIP,
    JOINT_INDEX_TIP,
)

# Import OpenXRSessionHandles from oxr module to avoid double registration
from ..oxr import OpenXRSessionHandles

__all__ = [
    "JointPose",
    "HandData",
    "HeadPose",
    "ITracker",
    "HandTracker",
    "HeadTracker",
    "OpenXRSessionHandles",
    "TeleopSessionBuilder",
    "TeleopSession",
    "NUM_JOINTS",
    "JOINT_PALM",
    "JOINT_WRIST",
    "JOINT_THUMB_TIP",
    "JOINT_INDEX_TIP",
]

