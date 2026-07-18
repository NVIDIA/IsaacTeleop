# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Basic tensor types for the retargeting engine."""

from .scalar_types import FloatType, IntType, BoolType
from .ndarray_types import NDArrayType, DLDeviceType, DLDataType
from .standard_types import (
    HandInput,
    HeadPose,
    ControllerInput,
    FullBodyInput,
    TransformMatrix,
    Generic3AxisPedalInput,
    NUM_HAND_JOINTS,
    NUM_BODY_JOINTS_PICO,
    RobotHandJoints,
)
from .tactile_types import (
    TactileVector,
    TactileHeatmap,
    FingerPowerVector,
    ControllerHapticPulse,
    EndEffectorForce,
    NUM_HAPTIC_FINGERS,
    NUM_CONTROLLER_HAPTIC_FIELDS,
    NUM_END_EFFECTOR_FORCE_AXES,
)
from .indices import (
    HandInputIndex,
    HeadPoseIndex,
    ControllerInputIndex,
    Generic3AxisPedalInputIndex,
    FullBodyInputIndex,
    HandJointIndex,
    BodyJointPicoIndex,
    FingerIndex,
    ControllerHapticPulseField,
    EndEffectorForceAxis,
)

__all__ = [
    "FloatType",
    "IntType",
    "BoolType",
    "NDArrayType",
    "DLDeviceType",
    "DLDataType",
    # Standard types
    "HandInput",
    "HeadPose",
    "ControllerInput",
    "FullBodyInput",
    "TransformMatrix",
    "Generic3AxisPedalInput",
    "NUM_HAND_JOINTS",
    "NUM_BODY_JOINTS_PICO",
    "RobotHandJoints",
    # Tactile / haptic types
    "TactileVector",
    "TactileHeatmap",
    "FingerPowerVector",
    "ControllerHapticPulse",
    "EndEffectorForce",
    "NUM_HAPTIC_FINGERS",
    "NUM_CONTROLLER_HAPTIC_FIELDS",
    "NUM_END_EFFECTOR_FORCE_AXES",
    # Indices
    "HandInputIndex",
    "HeadPoseIndex",
    "ControllerInputIndex",
    "Generic3AxisPedalInputIndex",
    "FullBodyInputIndex",
    "HandJointIndex",
    "BodyJointPicoIndex",
    "FingerIndex",
    "ControllerHapticPulseField",
    "EndEffectorForceAxis",
]
