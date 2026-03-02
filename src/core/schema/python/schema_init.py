# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Teleop Schema - FlatBuffer message types for teleoperation.

This module provides Python bindings for FlatBuffer-based message types
used in teleoperation, including poses, and controller data.
"""

from ._schema import (
    # Timestamp types.
    DeviceDataTimestamp,
    # Pose-related types (structs).
    Point,
    Quaternion,
    Pose,
    # Head-related types.
    HeadPoseT,
    HeadPoseTrackedT,
    HeadPoseRecord,
    # Hand-related types.
    HandJointPose,
    HandJoints,
    HandPoseT,
    HandPoseTrackedT,
    HandPoseRecord,
    # Controller-related types.
    ControllerInputState,
    ControllerPose,
    ControllerSnapshot,
    ControllerSnapshotTrackedT,
    ControllerSnapshotRecord,
    # Pedals-related types.
    Generic3AxisPedalOutput,
    Generic3AxisPedalOutputTrackedT,
    Generic3AxisPedalOutputRecord,
    # Camera-related types.
    StreamType,
    FrameMetadataOak,
    FrameMetadataOakTrackedT,
    FrameMetadataOakRecord,
    # Full body-related types.
    BodyJointPico,
    BodyJointPose,
    BodyJointsPico,
    FullBodyPosePicoT,
    FullBodyPosePicoTrackedT,
    FullBodyPosePicoRecord,
)


__all__ = [
    # Timestamp types.
    "DeviceDataTimestamp",
    # Pose types (structs).
    "Point",
    "Quaternion",
    "Pose",
    # Head types.
    "HeadPoseT",
    "HeadPoseTrackedT",
    "HeadPoseRecord",
    # Hand types.
    "HandJointPose",
    "HandJoints",
    "HandPoseT",
    "HandPoseTrackedT",
    "HandPoseRecord",
    # Controller types.
    "ControllerInputState",
    "ControllerPose",
    "ControllerSnapshot",
    "ControllerSnapshotTrackedT",
    "ControllerSnapshotRecord",
    # Pedals types.
    "Generic3AxisPedalOutput",
    "Generic3AxisPedalOutputTrackedT",
    "Generic3AxisPedalOutputRecord",
    # Camera types.
    "StreamType",
    "FrameMetadataOak",
    "FrameMetadataOakTrackedT",
    "FrameMetadataOakRecord",
    # Full body types.
    "BodyJointPose",
    "BodyJointsPico",
    "BodyJointPico",
    "FullBodyPosePicoT",
    "FullBodyPosePicoTrackedT",
    "FullBodyPosePicoRecord",
]
