# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""DeviceIO Source Nodes - Stateless converters from DeviceIO to retargeting engine formats."""

from .interface import IDeviceIOSource
from .head_source import HeadSource
from .hands_source import HandsSource
from .controllers_source import ControllersSource
from .pedals_source import Generic3AxisPedalSource
from .haply_source import HaplyDeviceSource
from .full_body_source import FullBodySource
from .deviceio_tensor_types import (
    HeadPoseTrackedType,
    HandPoseTrackedType,
    ControllerSnapshotTrackedType,
    Generic3AxisPedalOutputTrackedType,
    HaplyDeviceOutputTrackedType,
    FullBodyPosePicoTrackedType,
    DeviceIOHeadPoseTracked,
    DeviceIOHandPoseTracked,
    DeviceIOControllerSnapshotTracked,
    DeviceIOGeneric3AxisPedalOutputTracked,
    DeviceIOHaplyDeviceOutputTracked,
    DeviceIOFullBodyPosePicoTracked,
)

__all__ = [
    "IDeviceIOSource",
    "HeadSource",
    "HandsSource",
    "ControllersSource",
    "Generic3AxisPedalSource",
    "HaplyDeviceSource",
    "FullBodySource",
    "HeadPoseTrackedType",
    "HandPoseTrackedType",
    "ControllerSnapshotTrackedType",
    "Generic3AxisPedalOutputTrackedType",
    "HaplyDeviceOutputTrackedType",
    "FullBodyPosePicoTrackedType",
    "DeviceIOHeadPoseTracked",
    "DeviceIOHandPoseTracked",
    "DeviceIOControllerSnapshotTracked",
    "DeviceIOGeneric3AxisPedalOutputTracked",
    "DeviceIOHaplyDeviceOutputTracked",
    "DeviceIOFullBodyPosePicoTracked",
]
