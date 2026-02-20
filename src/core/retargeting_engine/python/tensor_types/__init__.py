# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
    NUM_HAND_JOINTS,
    NUM_BODY_JOINTS_PICO,
    RobotHandJoints,
)
from .indices import (
    HandInputIndex,
    ControllerInputIndex,
    FullBodyInputIndex,
    HandJointIndex,
    BodyJointPicoIndex,
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
    "NUM_HAND_JOINTS",
    "NUM_BODY_JOINTS_PICO",
    "RobotHandJoints",
    # Indices
    "HandInputIndex",
    "ControllerInputIndex",
    "FullBodyInputIndex",
    "HandJointIndex",
    "BodyJointPicoIndex",
]
