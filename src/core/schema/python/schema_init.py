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
    HandJoint,
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
    # OGLO tactile glove types.
    OgloGloveSample,
    OgloGloveSampleTrackedT,
    OgloGloveSampleRecord,
    # Joint-state types (generic joint-space devices: leader arms, exoskeletons, ...).
    JointState,
    JointStateOutput,
    JointStateOutputTrackedT,
    JointStateOutputRecord,
    # SE3 tracker types (generic 6-DoF pose sources: tracker pucks, mocap rigid bodies, ...).
    # Record classes drop the T suffix in Python by family convention.
    Se3TrackerPoseT,
    Se3TrackerPoseTrackedT,
    Se3TrackerPoseRecord,
    # Message channel types.
    MessageChannelMessages,
    MessageChannelMessagesTrackedT,
    MessageChannelMessagesRecord,
    # Haptic command types (vendor-neutral cross-process device output).
    HapticCommand,
    pack_haptic_command,
    # Camera-related types.
    StreamType,
    FrameMetadataOak,
    FrameMetadataOakTrackedT,
    FrameMetadataOakRecord,
    # Full body-related types.
    BodyJoint,
    BodyJointPose,
    BodyJoints,
    FullBodyPoseT,
    FullBodyPoseTrackedT,
    FullBodyPoseRecord,
)

# Deprecated aliases for the renamed full-body schema types (use the generic names above).
BodyJointPico = BodyJoint
BodyJointsPico = BodyJoints
FullBodyPosePicoT = FullBodyPoseT
FullBodyPosePicoTrackedT = FullBodyPoseTrackedT
FullBodyPosePicoRecord = FullBodyPoseRecord


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
    "HandJoint",
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
    # OGLO tactile glove types.
    "OgloGloveSample",
    "OgloGloveSampleTrackedT",
    "OgloGloveSampleRecord",
    # Joint-state types (generic joint-space devices).
    "JointState",
    "JointStateOutput",
    "JointStateOutputTrackedT",
    "JointStateOutputRecord",
    # SE3 tracker types (generic 6-DoF pose sources).
    "Se3TrackerPoseT",
    "Se3TrackerPoseTrackedT",
    "Se3TrackerPoseRecord",
    # Message channel types.
    "MessageChannelMessages",
    "MessageChannelMessagesTrackedT",
    "MessageChannelMessagesRecord",
    # Haptic command types.
    "HapticCommand",
    "pack_haptic_command",
    # Camera types.
    "StreamType",
    "FrameMetadataOak",
    "FrameMetadataOakTrackedT",
    "FrameMetadataOakRecord",
    # Full body types.
    "BodyJointPose",
    "BodyJoint",
    "BodyJoints",
    "FullBodyPoseT",
    "FullBodyPoseTrackedT",
    "FullBodyPoseRecord",
    # Deprecated full-body aliases.
    "BodyJointPico",
    "BodyJointsPico",
    "FullBodyPosePicoT",
    "FullBodyPosePicoTrackedT",
    "FullBodyPosePicoRecord",
]
