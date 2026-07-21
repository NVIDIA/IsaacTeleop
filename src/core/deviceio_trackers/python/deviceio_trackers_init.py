# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Teleop DeviceIO Trackers — tracker classes for device I/O."""

import warnings

from ._deviceio_trackers import (
    ITracker,
    HandTracker,
    HeadTracker,
    ControllerTracker,
    MessageChannelStatus,
    MessageChannelTracker,
    FrameMetadataTrackerOak,
    Generic3AxisPedalTracker,
    OgloTactileTracker,
    TensorPushTracker,
    JointStateTracker,
    Se3Tracker,
    FullBodyTracker,
    ITrackerSession,
    NUM_JOINTS,
    JOINT_PALM,
    JOINT_WRIST,
    JOINT_THUMB_TIP,
    JOINT_INDEX_TIP,
)

# Deprecated aliases resolved lazily via __getattr__ so that accessing them emits a
# DeprecationWarning. Intentionally omitted from __all__ so `import *` no longer pulls
# the old names.
_DEPRECATED_ALIASES = {"FullBodyTrackerPico": "FullBodyTracker"}


def __getattr__(name: str):
    new_name = _DEPRECATED_ALIASES.get(name)
    if new_name is not None:
        warnings.warn(
            f"{name} is deprecated; use {new_name} instead.",
            DeprecationWarning,
            stacklevel=2,
        )
        return globals()[new_name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = [
    "ControllerTracker",
    "MessageChannelStatus",
    "MessageChannelTracker",
    "FrameMetadataTrackerOak",
    "FullBodyTracker",
    "Generic3AxisPedalTracker",
    "OgloTactileTracker",
    "TensorPushTracker",
    "JointStateTracker",
    "HandTracker",
    "HeadTracker",
    "ITracker",
    "JOINT_INDEX_TIP",
    "JOINT_PALM",
    "JOINT_THUMB_TIP",
    "JOINT_WRIST",
    "NUM_JOINTS",
    "Se3Tracker",
    "ITrackerSession",
]
