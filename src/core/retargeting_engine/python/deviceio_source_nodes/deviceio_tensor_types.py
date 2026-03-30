# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
DeviceIO Tensor Types - Tracked wrapper objects from DeviceIO.

These tensor types represent the TrackedT wrapper objects returned by DeviceIO trackers.
Each TrackedT always exists (never None) and contains a `.data` property that holds
the raw flatbuffer object (or None when the tracker is inactive).
"""

from enum import IntEnum
from typing import Any
from ..interface.tensor_type import TensorType
from ..interface.tensor_group_type import TensorGroupType
from isaacteleop.schema import (
    HeadPoseTrackedT,
    HandPoseTrackedT,
    ControllerSnapshotTrackedT,
    Generic3AxisPedalOutputTrackedT,
    FullBodyPosePicoTrackedT,
    MessageChannelMessagesTrackedT,
)


class HeadPoseTrackedType(TensorType):
    """HeadPoseTrackedT wrapper type from DeviceIO HeadTracker."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        if not isinstance(other, HeadPoseTrackedType):
            raise TypeError(f"Expected HeadPoseTrackedType, got {type(other).__name__}")
        return True

    def validate_value(self, value: Any) -> None:
        if not isinstance(value, HeadPoseTrackedT):
            raise TypeError(
                f"Expected HeadPoseTrackedT for '{self.name}', got {type(value).__name__}"
            )


class HandPoseTrackedType(TensorType):
    """HandPoseTrackedT wrapper type from DeviceIO HandTracker."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        if not isinstance(other, HandPoseTrackedType):
            raise TypeError(f"Expected HandPoseTrackedType, got {type(other).__name__}")
        return True

    def validate_value(self, value: Any) -> None:
        if not isinstance(value, HandPoseTrackedT):
            raise TypeError(
                f"Expected HandPoseTrackedT for '{self.name}', got {type(value).__name__}"
            )


class ControllerSnapshotTrackedType(TensorType):
    """ControllerSnapshotTrackedT wrapper type from DeviceIO ControllerTracker."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        if not isinstance(other, ControllerSnapshotTrackedType):
            raise TypeError(
                f"Expected ControllerSnapshotTrackedType, got {type(other).__name__}"
            )
        return True

    def validate_value(self, value: Any) -> None:
        if not isinstance(value, ControllerSnapshotTrackedT):
            raise TypeError(
                f"Expected ControllerSnapshotTrackedT for '{self.name}', got {type(value).__name__}"
            )


class Generic3AxisPedalOutputTrackedType(TensorType):
    """Generic3AxisPedalOutputTrackedT wrapper type from DeviceIO Generic3AxisPedalTracker."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        if not isinstance(other, Generic3AxisPedalOutputTrackedType):
            raise TypeError(
                f"Expected Generic3AxisPedalOutputTrackedType, got {type(other).__name__}"
            )
        return True

    def validate_value(self, value: Any) -> None:
        if not isinstance(value, Generic3AxisPedalOutputTrackedT):
            raise TypeError(
                f"Expected Generic3AxisPedalOutputTrackedT for '{self.name}', got {type(value).__name__}"
            )


class FullBodyPosePicoTrackedType(TensorType):
    """FullBodyPosePicoTrackedT wrapper type from DeviceIO FullBodyTrackerPico."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        if not isinstance(other, FullBodyPosePicoTrackedType):
            raise TypeError(
                f"Expected FullBodyPosePicoTrackedType, got {type(other).__name__}"
            )
        return True

    def validate_value(self, value: Any) -> None:
        if not isinstance(value, FullBodyPosePicoTrackedT):
            raise TypeError(
                f"Expected FullBodyPosePicoTrackedT for '{self.name}', got {type(value).__name__}"
            )


class MessageChannelMessagesTrackedType(TensorType):
    """MessageChannelMessagesTrackedT wrapper type from DeviceIO MessageChannelTracker."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        if not isinstance(other, MessageChannelMessagesTrackedType):
            raise TypeError(
                f"Expected MessageChannelMessagesTrackedType, got {type(other).__name__}"
            )
        return True

    def validate_value(self, value: Any) -> None:
        if not isinstance(value, MessageChannelMessagesTrackedT):
            raise TypeError(
                f"Expected MessageChannelMessagesTrackedT for '{self.name}', got {type(value).__name__}"
            )


class MessageChannelConnectionStatus(IntEnum):
    """Message channel connection states exposed by MessageChannelSource."""

    CONNECTING = 0
    CONNECTED = 1
    SHUTTING = 2
    DISCONNECTED = 3
    UNKNOWN = -1


class MessageChannelStatusType(TensorType):
    """Enum status for message channel connectivity."""

    def __init__(self, name: str) -> None:
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        if not isinstance(other, MessageChannelStatusType):
            raise TypeError(
                f"Expected MessageChannelStatusType, got {type(other).__name__}"
            )
        return True

    def validate_value(self, value: Any) -> None:
        if not isinstance(value, MessageChannelConnectionStatus):
            raise TypeError(
                f"Expected MessageChannelConnectionStatus for '{self.name}', got {type(value).__name__}"
            )


def DeviceIOHeadPoseTracked() -> TensorGroupType:
    """Tracked head pose from DeviceIO HeadTracker.

    Contains:
        head_tracked: HeadPoseTrackedT wrapper (always set; .data is None when inactive)
    """
    return TensorGroupType("deviceio_head_pose", [HeadPoseTrackedType("head_tracked")])


def DeviceIOHandPoseTracked() -> TensorGroupType:
    """Tracked hand pose from DeviceIO HandTracker.

    Contains:
        hand_tracked: HandPoseTrackedT wrapper (always set; .data is None when inactive)
    """
    return TensorGroupType("deviceio_hand_pose", [HandPoseTrackedType("hand_tracked")])


def DeviceIOControllerSnapshotTracked() -> TensorGroupType:
    """Tracked controller snapshot from DeviceIO ControllerTracker.

    Contains:
        controller_tracked: ControllerSnapshotTrackedT wrapper (always set; .data is None when inactive)
    """
    return TensorGroupType(
        "deviceio_controller_snapshot",
        [ControllerSnapshotTrackedType("controller_tracked")],
    )


def DeviceIOGeneric3AxisPedalOutputTracked() -> TensorGroupType:
    """Tracked pedal data from DeviceIO Generic3AxisPedalTracker.

    Contains:
        pedal_tracked: Generic3AxisPedalOutputTrackedT wrapper (always set; .data is None when inactive)
    """
    return TensorGroupType(
        "deviceio_generic_3axis_pedal_output",
        [Generic3AxisPedalOutputTrackedType("pedal_tracked")],
    )


def DeviceIOFullBodyPosePicoTracked() -> TensorGroupType:
    """Tracked full body pose data from DeviceIO FullBodyTrackerPico.

    Contains:
        full_body_tracked: FullBodyPosePicoTrackedT wrapper (always set; .data is None when inactive)
    """
    return TensorGroupType(
        "deviceio_full_body_pose_pico",
        [FullBodyPosePicoTrackedType("full_body_tracked")],
    )


def DeviceIOMessageChannelMessagesTracked() -> TensorGroupType:
    """Tracked message wrapper from DeviceIO MessageChannelTracker."""
    return TensorGroupType(
        "deviceio_message_channel_messages_tracked",
        [MessageChannelMessagesTrackedType("messages_tracked")],
    )


def MessageChannelMessagesTrackedGroup() -> TensorGroupType:
    """Tracked batch of messages drained in one update."""
    return TensorGroupType(
        "message_channel_messages_tracked",
        [MessageChannelMessagesTrackedType("messages_tracked")],
    )


def MessageChannelStatusGroup() -> TensorGroupType:
    """Message channel connection status enum."""
    return TensorGroupType(
        "message_channel_status",
        [MessageChannelStatusType("status")],
    )
