# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Controller types in isaacteleop.schema.

Tests the following FlatBuffers types:
- ControllerInputState: Struct with button and axis inputs (immutable)
- ControllerPose: Struct with pose and validity (immutable)
- Timestamp: Struct with device and common time timestamps (immutable)
- ControllerSnapshot: Table representing complete controller state
- ControllerData: Root table with both left and right controllers
"""

import pytest

from isaacteleop.schema import (
    ControllerInputState,
    ControllerPose,
    Timestamp,
    ControllerSnapshot,
    ControllerData,
    Pose,
    Point,
    Quaternion,
)


class TestControllerInputState:
    """Tests for ControllerInputState struct (immutable)."""

    def test_default_construction(self):
        """Test default construction creates ControllerInputState with default values."""
        inputs = ControllerInputState()

        assert inputs is not None
        assert inputs.primary_click is False
        assert inputs.secondary_click is False
        assert inputs.thumbstick_click is False
        assert inputs.thumbstick_x == pytest.approx(0.0)
        assert inputs.thumbstick_y == pytest.approx(0.0)
        assert inputs.squeeze_value == pytest.approx(0.0)
        assert inputs.trigger_value == pytest.approx(0.0)

    def test_button_states(self):
        """Test constructing with button states."""
        inputs = ControllerInputState(
            primary_click=True, secondary_click=True, thumbstick_click=True, thumbstick_x=0.0, thumbstick_y=0.0, squeeze_value=0.0, trigger_value=0.0
        )

        assert inputs.primary_click is True
        assert inputs.secondary_click is True
        assert inputs.thumbstick_click is True

    def test_analog_values(self):
        """Test constructing with analog axis values."""
        inputs = ControllerInputState(
            primary_click=False,
            secondary_click=False,
            thumbstick_click=False,
            thumbstick_x=0.5,
            thumbstick_y=-0.75,
            squeeze_value=0.8,
            trigger_value=1.0,
        )

        assert inputs.thumbstick_x == pytest.approx(0.5)
        assert inputs.thumbstick_y == pytest.approx(-0.75)
        assert inputs.squeeze_value == pytest.approx(0.8)
        assert inputs.trigger_value == pytest.approx(1.0)

    def test_repr(self):
        """Test __repr__ method."""
        inputs = ControllerInputState(
            primary_click=True, secondary_click=False, thumbstick_click=False, thumbstick_x=0.0, thumbstick_y=0.0, squeeze_value=0.0, trigger_value=0.5
        )

        repr_str = repr(inputs)
        assert "ControllerInputState" in repr_str
        assert "primary=True" in repr_str


class TestTimestamp:
    """Tests for Timestamp struct (immutable)."""

    def test_default_construction(self):
        """Test default construction creates Timestamp with default values."""
        timestamp = Timestamp()

        assert timestamp is not None
        assert timestamp.device_time == 0
        assert timestamp.common_time == 0

    def test_set_timestamp_values(self):
        """Test constructing with timestamp values."""
        timestamp = Timestamp(device_time=1234567890123456789, common_time=9876543210)

        assert timestamp.device_time == 1234567890123456789
        assert timestamp.common_time == 9876543210

    def test_large_timestamp_values(self):
        """Test with large int64 timestamp values."""
        max_int64 = 9223372036854775807
        timestamp = Timestamp(device_time=max_int64, common_time=max_int64 - 1000)

        assert timestamp.device_time == max_int64
        assert timestamp.common_time == max_int64 - 1000

    def test_repr(self):
        """Test __repr__ method."""
        timestamp = Timestamp(device_time=1000, common_time=2000)

        repr_str = repr(timestamp)
        assert "Timestamp" in repr_str
        assert "device_time=1000" in repr_str
        assert "common_time=2000" in repr_str


class TestControllerPose:
    """Tests for ControllerPose struct (immutable)."""

    def test_default_construction(self):
        """Test default construction creates ControllerPose with default values."""
        controller_pose = ControllerPose()

        assert controller_pose is not None
        # Structs always have default values, never None
        assert controller_pose.pose is not None
        assert controller_pose.is_valid is False

    def test_construction_with_pose(self):
        """Test constructing with pose data."""
        position = Point(1.0, 2.0, 3.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        pose = Pose(position, orientation)
        controller_pose = ControllerPose(True, pose)

        assert controller_pose.pose.position.x == pytest.approx(1.0)
        assert controller_pose.pose.position.y == pytest.approx(2.0)
        assert controller_pose.pose.position.z == pytest.approx(3.0)
        assert controller_pose.pose.orientation.w == pytest.approx(1.0)
        assert controller_pose.is_valid is True

    def test_is_valid_flag(self):
        """Test is_valid flag."""
        position = Point(0.0, 0.0, 0.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        pose = Pose(position, orientation)
        controller_pose = ControllerPose(True, pose)

        assert controller_pose.is_valid is True

    def test_pose_with_rotation(self):
        """Test pose with a rotation quaternion."""
        position = Point(0.0, 0.0, 0.0)
        # 90-degree rotation around Z axis
        orientation = Quaternion(0.0, 0.0, 0.7071068, 0.7071068)
        pose = Pose(position, orientation)
        controller_pose = ControllerPose(True, pose)

        assert controller_pose.pose.orientation.z == pytest.approx(0.7071068, abs=1e-5)
        assert controller_pose.pose.orientation.w == pytest.approx(0.7071068, abs=1e-5)
        assert controller_pose.is_valid is True

    def test_repr_without_valid_pose(self):
        """Test __repr__ when pose is not valid."""
        controller_pose = ControllerPose()
        repr_str = repr(controller_pose)

        assert "ControllerPose" in repr_str
        assert "is_valid=False" in repr_str

    def test_repr_with_pose(self):
        """Test __repr__ when pose is set."""
        position = Point(1.0, 2.0, 3.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        pose = Pose(position, orientation)
        controller_pose = ControllerPose(True, pose)

        repr_str = repr(controller_pose)
        assert "ControllerPose" in repr_str
        assert "is_valid=True" in repr_str


class TestControllerSnapshot:
    """Tests for ControllerSnapshot table (ControllerSnapshotT in C++)."""

    def test_default_construction(self):
        """Test default construction creates ControllerSnapshot with default values."""
        snapshot = ControllerSnapshot()

        assert snapshot is not None
        assert snapshot.is_valid is False
        # Table type: optional nested fields are None when not set
        assert snapshot.grip_pose is None
        assert snapshot.aim_pose is None
        assert snapshot.inputs is None
        assert snapshot.timestamp is None

    def test_complete_snapshot(self):
        """Test creating a complete controller snapshot with all fields."""
        # Create poses
        grip_position = Point(0.1, 0.2, 0.3)
        grip_orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        grip_pose_data = Pose(grip_position, grip_orientation)
        grip_pose = ControllerPose(True, grip_pose_data)

        aim_position = Point(0.15, 0.25, 0.35)
        aim_orientation = Quaternion(0.0, 0.1, 0.0, 0.99)
        aim_pose_data = Pose(aim_position, aim_orientation)
        aim_pose = ControllerPose(True, aim_pose_data)

        # Create inputs
        inputs = ControllerInputState(
            primary_click=True,
            secondary_click=False,
            thumbstick_click=True,
            thumbstick_x=0.5,
            thumbstick_y=-0.5,
            squeeze_value=0.75,
            trigger_value=1.0,
        )

        # Create timestamp
        timestamp = Timestamp(device_time=1000000000, common_time=2000000000)

        # Create snapshot
        snapshot = ControllerSnapshot(True, grip_pose, aim_pose, inputs, timestamp)

        # Verify all fields
        assert snapshot.grip_pose.is_valid is True
        assert snapshot.grip_pose.pose.position.x == pytest.approx(0.1)
        assert snapshot.aim_pose.is_valid is True
        assert snapshot.aim_pose.pose.position.x == pytest.approx(0.15)
        assert snapshot.inputs.primary_click is True
        assert snapshot.inputs.trigger_value == pytest.approx(1.0)
        assert snapshot.is_valid is True
        assert snapshot.timestamp.device_time == 1000000000
        assert snapshot.timestamp.common_time == 2000000000

    def test_repr_with_default(self):
        """Test __repr__ with default values."""
        snapshot = ControllerSnapshot()
        repr_str = repr(snapshot)

        assert "ControllerSnapshot" in repr_str
        assert "is_valid=False" in repr_str


class TestControllerData:
    """Tests for ControllerData table."""

    def test_default_construction(self):
        """Test default construction creates ControllerData with None controllers."""
        controller_data = ControllerData()

        assert controller_data is not None
        assert controller_data.left_controller is None
        assert controller_data.right_controller is None

    def test_repr(self):
        """Test __repr__ method."""
        controller_data = ControllerData()
        repr_str = repr(controller_data)

        assert "ControllerData" in repr_str


class TestControllerIntegration:
    """Integration tests combining multiple controller types."""

    def test_left_and_right_different_states(self):
        """Test that left and right controllers can have different states."""
        # Create left controller (active)
        left_position = Point(-0.2, 0.0, 0.0)
        left_orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        left_pose_data = Pose(left_position, left_orientation)
        left_grip = ControllerPose(True, left_pose_data)
        left_aim = ControllerPose(True, left_pose_data)
        left_inputs = ControllerInputState(
            primary_click=True,
            secondary_click=False,
            thumbstick_click=False,
            thumbstick_x=0.0,
            thumbstick_y=0.0,
            squeeze_value=0.0,
            trigger_value=0.5,
        )
        left_timestamp = Timestamp(device_time=1000, common_time=2000)
        left_snapshot = ControllerSnapshot(True, left_grip, left_aim, left_inputs, left_timestamp)

        # Create right controller (inactive)
        right_snapshot = ControllerSnapshot()

        # Verify different states
        assert left_snapshot.is_valid is True
        assert right_snapshot.is_valid is False
        assert left_snapshot.inputs.trigger_value == pytest.approx(0.5)
        # Default-constructed snapshot has optional fields; inputs may be None
        assert right_snapshot.inputs is None or right_snapshot.inputs.trigger_value == pytest.approx(0.0)

    def test_inactive_controller(self):
        """Test representing an inactive controller."""
        snapshot = ControllerSnapshot()

        assert snapshot.is_valid is False
        # Optional pose fields may be None for default-constructed inactive snapshot
        if snapshot.grip_pose is not None:
            assert snapshot.grip_pose.is_valid is False
        if snapshot.aim_pose is not None:
            assert snapshot.aim_pose.is_valid is False


class TestControllerEdgeCases:
    """Edge case tests for controller types."""

    def test_zero_analog_values(self):
        """Test with all analog values at zero (centered/released)."""
        inputs = ControllerInputState(
            primary_click=False,
            secondary_click=False,
            thumbstick_click=False,
            thumbstick_x=0.0,
            thumbstick_y=0.0,
            squeeze_value=0.0,
            trigger_value=0.0,
        )

        assert inputs.thumbstick_x == pytest.approx(0.0)
        assert inputs.thumbstick_y == pytest.approx(0.0)
        assert inputs.squeeze_value == pytest.approx(0.0)
        assert inputs.trigger_value == pytest.approx(0.0)

    def test_max_analog_values(self):
        """Test with all analog values at maximum."""
        inputs = ControllerInputState(
            primary_click=False,
            secondary_click=False,
            thumbstick_click=False,
            thumbstick_x=1.0,
            thumbstick_y=1.0,
            squeeze_value=1.0,
            trigger_value=1.0,
        )

        assert inputs.thumbstick_x == pytest.approx(1.0)
        assert inputs.thumbstick_y == pytest.approx(1.0)
        assert inputs.squeeze_value == pytest.approx(1.0)
        assert inputs.trigger_value == pytest.approx(1.0)

    def test_negative_analog_values(self):
        """Test with negative analog values (valid for thumbstick)."""
        inputs = ControllerInputState(
            primary_click=False,
            secondary_click=False,
            thumbstick_click=False,
            thumbstick_x=-1.0,
            thumbstick_y=-1.0,
            squeeze_value=0.0,
            trigger_value=0.0,
        )

        assert inputs.thumbstick_x == pytest.approx(-1.0)
        assert inputs.thumbstick_y == pytest.approx(-1.0)

    def test_invalid_pose(self):
        """Test controller pose with is_valid=False."""
        position = Point(1.0, 2.0, 3.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        pose = Pose(position, orientation)
        controller_pose = ControllerPose(False, pose)

        assert controller_pose.is_valid is False
        # Pose data is still present even if not valid
        assert controller_pose.pose.position.x == pytest.approx(1.0)

    def test_zero_timestamp(self):
        """Test with zero timestamp values."""
        timestamp = Timestamp(device_time=0, common_time=0)

        assert timestamp.device_time == 0
        assert timestamp.common_time == 0

    def test_negative_timestamp(self):
        """Test with negative timestamp values (valid for relative times)."""
        timestamp = Timestamp(device_time=-1000, common_time=-2000)

        assert timestamp.device_time == -1000
        assert timestamp.common_time == -2000
