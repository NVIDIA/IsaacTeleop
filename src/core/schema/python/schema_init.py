# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Teleop Schema - FlatBuffer message types for teleoperation.

This module provides Python bindings for FlatBuffer-based message types
used in teleoperation, including poses, and controller data.
"""

from ._schema import (
    # Pose-related types (structs).
    Point,
    Quaternion,
    Pose,
    # Head-related types.
    HeadPoseT,
    HeadPoseTrackedT,
    # Hand-related types.
    HandJointPose,
    HandJoints,
    HandPoseT,
    HandPoseTrackedT,
    # Controller-related types.
    ControllerInputState,
    ControllerPose,
    Timestamp,
    ControllerSnapshot,
    ControllerSnapshotTrackedT,
    # Locomotion-related types.
    Twist,
    LocomotionCommand,
    LocomotionCommandTrackedT,
    # Pedals-related types.
    Generic3AxisPedalOutput,
    Generic3AxisPedalOutputTrackedT,
    # Camera-related types.
    StreamType,
    FrameMetadataOak,
    FrameMetadataOakTrackedT,
    # Full body-related types.
    BodyJointPico,
    BodyJointPose,
    BodyJointsPico,
    FullBodyPosePicoT,
    FullBodyPosePicoTrackedT,
)


__all__ = [
    # Pose types (structs).
    "Point",
    "Quaternion",
    "Pose",
    # Head types.
    "HeadPoseT",
    "HeadPoseTrackedT",
    # Hand types.
    "HandJointPose",
    "HandJoints",
    "HandPoseT",
    "HandPoseTrackedT",
    # Controller types.
    "ControllerInputState",
    "ControllerPose",
    "Timestamp",
    "ControllerSnapshot",
    "ControllerSnapshotTrackedT",
    # Locomotion types.
    "Twist",
    "LocomotionCommand",
    "LocomotionCommandTrackedT",
    # Pedals types.
    "Generic3AxisPedalOutput",
    "Generic3AxisPedalOutputTrackedT",
    # Camera types.
    "StreamType",
    "FrameMetadataOak",
    "FrameMetadataOakTrackedT",
    # Full body types.
    "BodyJointPose",
    "BodyJointsPico",
    "BodyJointPico",
    "FullBodyPosePicoT",
    "FullBodyPosePicoTrackedT",
]
