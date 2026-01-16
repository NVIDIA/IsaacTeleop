# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
Dynamically generated indices for standard TensorGroupTypes.

This module provides IntEnum classes for indexing into standard tensor groups
(HandInput, ControllerInput) and standard joint arrays (HandJointIndex).

The indices for TensorGroupTypes are generated automatically from the type definitions
to ensure they always match the schema.
"""

from enum import IntEnum
from .standard_types import HandInput, ControllerInput

def _create_index_enum(name: str, group_type, prefix: str = "") -> IntEnum:
    """Helper to create an IntEnum from a TensorGroupType."""
    members = {}
    for i, t in enumerate(group_type.types):
        key = t.name
        if prefix and key.startswith(prefix):
            key = key[len(prefix):]
        members[key.upper()] = i
    return IntEnum(name, members)

# Generate indices dynamically
HandInputIndex = _create_index_enum("HandInputIndex", HandInput(), "hand_")
ControllerInputIndex = _create_index_enum("ControllerInputIndex", ControllerInput(), "controller_")

class HandJointIndex(IntEnum):
    """Indices for OpenXR hand joints (XR_HAND_JOINT_COUNT_EXT = 26)."""
    PALM = 0
    WRIST = 1
    THUMB_METACARPAL = 2
    THUMB_PROXIMAL = 3
    THUMB_DISTAL = 4
    THUMB_TIP = 5
    INDEX_METACARPAL = 6
    INDEX_PROXIMAL = 7
    INDEX_INTERMEDIATE = 8
    INDEX_DISTAL = 9
    INDEX_TIP = 10
    MIDDLE_METACARPAL = 11
    MIDDLE_PROXIMAL = 12
    MIDDLE_INTERMEDIATE = 13
    MIDDLE_DISTAL = 14
    MIDDLE_TIP = 15
    RING_METACARPAL = 16
    RING_PROXIMAL = 17
    RING_INTERMEDIATE = 18
    RING_DISTAL = 19
    RING_TIP = 20
    LITTLE_METACARPAL = 21
    LITTLE_PROXIMAL = 22
    LITTLE_INTERMEDIATE = 23
    LITTLE_DISTAL = 24
    LITTLE_TIP = 25

