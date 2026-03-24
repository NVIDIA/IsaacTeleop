# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Isaac Teleop DEVICEIO - Device I/O Module (backward-compatible re-exports)

Prefer importing directly:
    from isaacteleop.deviceio_trackers import HeadTracker, HandTracker
    from isaacteleop.deviceio_session import DeviceIOSession, McapRecordingConfig
"""

from isaacteleop.deviceio_trackers import (
    ITracker,
    HandTracker,
    HeadTracker,
    ControllerTracker,
    FrameMetadataTrackerOak,
    Generic3AxisPedalTracker,
    FullBodyTrackerPico,
)

from isaacteleop.deviceio_session import DeviceIOSession, McapRecordingConfig

from ..oxr import OpenXRSessionHandles

from ..schema import (
    ControllerInputState,
    ControllerPose,
    ControllerSnapshot,
    DeviceDataTimestamp,
    HandJoint,
    StreamType,
    FrameMetadataOak,
    Generic3AxisPedalOutput,
)

__all__ = [
    "ControllerInputState",
    "ControllerPose",
    "ControllerSnapshot",
    "DeviceDataTimestamp",
    "HandJoint",
    "StreamType",
    "FrameMetadataOak",
    "Generic3AxisPedalOutput",
    "ITracker",
    "HandTracker",
    "HeadTracker",
    "ControllerTracker",
    "FrameMetadataTrackerOak",
    "Generic3AxisPedalTracker",
    "FullBodyTrackerPico",
    "OpenXRSessionHandles",
    "DeviceIOSession",
    "McapRecordingConfig",
]
