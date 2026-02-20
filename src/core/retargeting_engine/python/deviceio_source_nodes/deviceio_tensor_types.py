# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""
DeviceIO Tensor Types - Raw flatbuffer data from DeviceIO.

These tensor types represent the raw flatbuffer schema objects returned by DeviceIO trackers
before conversion to the standard retargeting engine format.
"""

from typing import Any
from ..interface.tensor_type import TensorType
from ..interface.tensor_group_type import TensorGroupType
from isaacteleop.schema import (
    HeadPoseT,
    HandPoseT,
    ControllerSnapshot,
    Generic3AxisPedalOutput,
    FullBodyPosePicoT,
)


class HeadPoseTType(TensorType):
    """HeadPoseT flatbuffer schema type."""

    def __init__(self, name: str) -> None:
        """
        Initialize a HeadPoseT type.

        Args:
            name: Name for this tensor
        """
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """HeadPoseT types are always compatible with other HeadPoseT types."""
        assert isinstance(other, HeadPoseTType), (
            f"Expected HeadPoseTType, got {type(other).__name__}"
        )
        return True

    def validate_value(self, value: Any) -> None:
        """
        Validate if the given value is a HeadPoseT schema object.

        Raises:
            TypeError: If value is not a HeadPoseT
        """
        if not isinstance(value, HeadPoseT):
            raise TypeError(
                f"Expected HeadPoseT for '{self.name}', got {type(value).__name__}"
            )


class HandPoseTType(TensorType):
    """HandPoseT flatbuffer schema type."""

    def __init__(self, name: str) -> None:
        """
        Initialize a HandPoseT type.

        Args:
            name: Name for this tensor
        """
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """HandPoseT types are always compatible with other HandPoseT types."""
        assert isinstance(other, HandPoseTType), (
            f"Expected HandPoseTType, got {type(other).__name__}"
        )
        return True

    def validate_value(self, value: Any) -> None:
        """
        Validate if the given value is a HandPoseT schema object.

        Raises:
            TypeError: If value is not a HandPoseT
        """
        if not isinstance(value, HandPoseT):
            raise TypeError(
                f"Expected HandPoseT for '{self.name}', got {type(value).__name__}"
            )


class ControllerSnapshotType(TensorType):
    """ControllerSnapshot flatbuffer schema type."""

    def __init__(self, name: str) -> None:
        """
        Initialize a ControllerSnapshot type.

        Args:
            name: Name for this tensor
        """
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """ControllerSnapshot types are always compatible with other ControllerSnapshot types."""
        assert isinstance(other, ControllerSnapshotType), (
            f"Expected ControllerSnapshotType, got {type(other).__name__}"
        )
        return True

    def validate_value(self, value: Any) -> None:
        """
        Validate if the given value is a ControllerSnapshot schema object.

        Raises:
            TypeError: If value is not a ControllerSnapshot
        """
        if not isinstance(value, ControllerSnapshot):
            raise TypeError(
                f"Expected ControllerSnapshot for '{self.name}', got {type(value).__name__}"
            )


class Generic3AxisPedalOutputType(TensorType):
    """Generic3AxisPedalOutput flatbuffer schema type (Generic3AxisPedalOutputT from tracker)."""

    def __init__(self, name: str) -> None:
        """
        Initialize a Generic3AxisPedalOutput type.

        Args:
            name: Name for this tensor
        """
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """Generic3AxisPedalOutput types are always compatible with other Generic3AxisPedalOutput types."""
        assert isinstance(other, Generic3AxisPedalOutputType), (
            f"Expected Generic3AxisPedalOutputType, got {type(other).__name__}"
        )
        return True

    def validate_value(self, value: Any) -> None:
        """
        Validate if the given value is a Generic3AxisPedalOutput schema object.

        Raises:
            TypeError: If value is not a Generic3AxisPedalOutput
        """
        if not isinstance(value, Generic3AxisPedalOutput):
            raise TypeError(
                f"Expected Generic3AxisPedalOutput for '{self.name}', got {type(value).__name__}"
            )


class FullBodyPosePicoTType(TensorType):
    """FullBodyPosePicoT flatbuffer schema type."""

    def __init__(self, name: str) -> None:
        """
        Initialize a FullBodyPosePicoT type.

        Args:
            name: Name for this tensor
        """
        super().__init__(name)

    def _check_instance_compatibility(self, other: TensorType) -> bool:
        """FullBodyPosePicoT types are always compatible with other FullBodyPosePicoT types."""
        assert isinstance(other, FullBodyPosePicoTType), (
            f"Expected FullBodyPosePicoTType, got {type(other).__name__}"
        )
        return True

    def validate_value(self, value: Any) -> None:
        """
        Validate if the given value is a FullBodyPosePicoT schema object.

        Raises:
            TypeError: If value is not a FullBodyPosePicoT
        """
        if not isinstance(value, FullBodyPosePicoT):
            raise TypeError(
                f"Expected FullBodyPosePicoT for '{self.name}', got {type(value).__name__}"
            )


def DeviceIOHeadPose() -> TensorGroupType:
    """Raw head pose data from DeviceIO HeadTracker.

    Contains:
        head_data: HeadPoseT flatbuffer schema object
    """
    return TensorGroupType("deviceio_head_pose", [HeadPoseTType("head_data")])


def DeviceIOHandPose() -> TensorGroupType:
    """Raw hand pose data from DeviceIO HandTracker.

    Contains:
        hand_data: HandPoseT flatbuffer schema object
    """
    return TensorGroupType("deviceio_hand_pose", [HandPoseTType("hand_data")])


def DeviceIOControllerSnapshot() -> TensorGroupType:
    """Raw controller snapshot from DeviceIO ControllerTracker.

    Contains:
        controller_data: ControllerSnapshot flatbuffer schema object
    """
    return TensorGroupType(
        "deviceio_controller_snapshot", [ControllerSnapshotType("controller_data")]
    )


def DeviceIOGeneric3AxisPedalOutput() -> TensorGroupType:
    """Raw pedal data from DeviceIO Generic3AxisPedalTracker.

    Contains:
        pedal_data: Generic3AxisPedalOutput (Generic3AxisPedalOutputT) flatbuffer schema object
    """
    return TensorGroupType(
        "deviceio_generic_3axis_pedal_output",
        [Generic3AxisPedalOutputType("pedal_data")],
    )


def DeviceIOFullBodyPosePico() -> TensorGroupType:
    """Raw full body pose data from DeviceIO FullBodyTrackerPico.

    Contains:
        full_body_data: FullBodyPosePicoT flatbuffer schema object
    """
    return TensorGroupType(
        "deviceio_full_body_pose_pico",
        [FullBodyPosePicoTType("full_body_data")],
    )
