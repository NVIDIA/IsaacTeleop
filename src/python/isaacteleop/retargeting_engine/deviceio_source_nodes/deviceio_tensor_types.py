# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
DeviceIO Tensor Types - payload handles from DeviceIO trackers.

These tensor types represent the encoded payloads returned by DeviceIO trackers.
Each carries a handle over the encoded payload, read directly through the schema
accessors. An inactive device arrives as None rather than as an empty handle.
"""

import warnings
from enum import IntEnum
from typing import Any
from ..interface.tensor_type import TensorType
from ..interface.tensor_group_type import TensorGroupType
from isaacteleop.schema import (
    HeadPose,
    HandPose,
    ControllerSnapshot,
    Generic3AxisPedalOutput,
    JointStateOutput,
    FullBodyPose,
    MessageChannelMessagesTracked,
)


def _payload_tensor_type(class_name: str, payload_cls: type, doc: str) -> type:
    """Build the ``TensorType`` subclass carrying one DeviceIO payload handle.

    Every payload validates the same way, so the class name and the payload class
    are the only things that vary between them.
    """

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        if not isinstance(other, cls):
            raise TypeError(f"Expected {class_name}, got {type(other).__name__}")
        return True

    def validate_value(self, value: Any) -> None:
        # None is how an inactive device arrives; only a wrong type is an error.
        if value is not None and not isinstance(value, payload_cls):
            raise TypeError(
                f"Expected {payload_cls.__name__} for '{self.name}', got {type(value).__name__}"
            )

    cls = type(
        class_name,
        (TensorType,),
        {
            "__doc__": doc,
            "__module__": __name__,
            "_check_instance_compatibility": _check_instance_compatibility,
            "validate_value": validate_value,
        },
    )
    return cls


HeadPoseTrackedType = _payload_tensor_type(
    "HeadPoseTrackedType", HeadPose, "HeadPose wrapper type from DeviceIO HeadTracker."
)

HandPoseTrackedType = _payload_tensor_type(
    "HandPoseTrackedType", HandPose, "HandPose wrapper type from DeviceIO HandTracker."
)

ControllerSnapshotTrackedType = _payload_tensor_type(
    "ControllerSnapshotTrackedType",
    ControllerSnapshot,
    "ControllerSnapshot wrapper type from DeviceIO ControllerTracker.",
)

Generic3AxisPedalOutputTrackedType = _payload_tensor_type(
    "Generic3AxisPedalOutputTrackedType",
    Generic3AxisPedalOutput,
    "Generic3AxisPedalOutput wrapper type from DeviceIO Generic3AxisPedalTracker.",
)

JointStateOutputTrackedType = _payload_tensor_type(
    "JointStateOutputTrackedType",
    JointStateOutput,
    "JointStateOutput wrapper type from DeviceIO JointStateTracker.",
)

FullBodyPoseTrackedType = _payload_tensor_type(
    "FullBodyPoseTrackedType",
    FullBodyPose,
    """FullBodyPose wrapper type from DeviceIO FullBodyTracker.

    Vendor-agnostic: the full-body tracker produces the same FullBodyPose
    payload regardless of the live vendor (native XR, pushed tensor, ...).
    """,
)

MessageChannelMessagesTrackedType = _payload_tensor_type(
    "MessageChannelMessagesTrackedType",
    MessageChannelMessagesTracked,
    "MessageChannelMessagesTracked wrapper type from DeviceIO MessageChannelTracker.",
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
        # Not a device payload: MessageChannelSource always assigns a status. None is
        # tolerated only so an unset slot validates like the payload types above.
        if value is not None and not isinstance(value, MessageChannelConnectionStatus):
            raise TypeError(
                f"Expected MessageChannelConnectionStatus for '{self.name}', got {type(value).__name__}"
            )


def DeviceIOHeadPoseTracked() -> TensorGroupType:
    """Tracked head pose from DeviceIO HeadTracker.

    Contains:
        head_tracked: HeadPose handle, or None when inactive
    """
    return TensorGroupType("deviceio_head_pose", [HeadPoseTrackedType("head_tracked")])


def DeviceIOHandPoseTracked() -> TensorGroupType:
    """Tracked hand pose from DeviceIO HandTracker.

    Contains:
        hand_tracked: HandPose handle, or None when inactive
    """
    return TensorGroupType("deviceio_hand_pose", [HandPoseTrackedType("hand_tracked")])


def DeviceIOControllerSnapshotTracked() -> TensorGroupType:
    """Tracked controller snapshot from DeviceIO ControllerTracker.

    Contains:
        controller_tracked: ControllerSnapshot handle, or None when inactive
    """
    return TensorGroupType(
        "deviceio_controller_snapshot",
        [ControllerSnapshotTrackedType("controller_tracked")],
    )


def DeviceIOGeneric3AxisPedalOutputTracked() -> TensorGroupType:
    """Tracked pedal data from DeviceIO Generic3AxisPedalTracker.

    Contains:
        pedal_tracked: Generic3AxisPedalOutput handle, or None when inactive
    """
    return TensorGroupType(
        "deviceio_generic_3axis_pedal_output",
        [Generic3AxisPedalOutputTrackedType("pedal_tracked")],
    )


def DeviceIOJointStateOutputTracked() -> TensorGroupType:
    """Tracked joint-state data from DeviceIO JointStateTracker.

    Contains:
        joint_state_tracked: JointStateOutput handle, or None when inactive
    """
    return TensorGroupType(
        "deviceio_joint_state_output",
        [JointStateOutputTrackedType("joint_state_tracked")],
    )


def DeviceIOFullBodyPoseTracked() -> TensorGroupType:
    """Tracked full body pose data from DeviceIO FullBodyTracker.

    Contains:
        full_body_tracked: FullBodyPose handle, or None when inactive
    """
    return TensorGroupType(
        "deviceio_full_body_pose",
        [FullBodyPoseTrackedType("full_body_tracked")],
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


# Deprecated aliases resolved lazily via __getattr__ so accessing them emits a
# DeprecationWarning.
_DEPRECATED_ALIASES = {
    "FullBodyPosePicoTrackedType": "FullBodyPoseTrackedType",
    "DeviceIOFullBodyPosePicoTracked": "DeviceIOFullBodyPoseTracked",
}


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
