# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Controller types in isaacteleop.schema.

Tests the following FlatBuffers types:
- ControllerInputState: Struct with button and axis inputs (immutable)
- ControllerPose: Struct with pose and validity (immutable)
- ControllerSnapshot: Table representing complete controller state
"""

import pytest

from isaacteleop.schema import (
    ControllerInputState,
    ControllerPose,
    ControllerSnapshot,
    ControllerSnapshotRecord,
    Pose,
    Point,
    Quaternion,
    DeviceDataTimestamp,
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
            primary_click=True,
            secondary_click=True,
            thumbstick_click=True,
            thumbstick_x=0.0,
            thumbstick_y=0.0,
            squeeze_value=0.0,
            trigger_value=0.0,
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
            primary_click=True,
            secondary_click=False,
            thumbstick_click=False,
            thumbstick_x=0.0,
            thumbstick_y=0.0,
            squeeze_value=0.0,
            trigger_value=0.5,
        )

        repr_str = repr(inputs)
        assert "ControllerInputState" in repr_str
        assert "primary=True" in repr_str


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
        controller_pose = ControllerPose(pose, True)

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
        controller_pose = ControllerPose(pose, True)

        assert controller_pose.is_valid is True

    def test_pose_with_rotation(self):
        """Test pose with a rotation quaternion."""
        position = Point(0.0, 0.0, 0.0)
        # 90-degree rotation around Z axis
        orientation = Quaternion(0.0, 0.0, 0.7071068, 0.7071068)
        pose = Pose(position, orientation)
        controller_pose = ControllerPose(pose, True)

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
        controller_pose = ControllerPose(pose, True)

        repr_str = repr(controller_pose)
        assert "ControllerPose" in repr_str
        assert "is_valid=True" in repr_str


class TestControllerSnapshot:
    """Tests for ControllerSnapshot table."""

    def test_default_construction(self):
        """Test default construction creates ControllerSnapshot with default values."""
        snapshot = ControllerSnapshot()

        assert snapshot is not None
        assert snapshot.grip_pose is not None
        assert snapshot.aim_pose is not None
        assert snapshot.inputs is not None

    def test_complete_snapshot(self):
        """Test creating a complete controller snapshot with all fields."""
        # Create poses
        grip_position = Point(0.1, 0.2, 0.3)
        grip_orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        grip_pose_data = Pose(grip_position, grip_orientation)
        grip_pose = ControllerPose(grip_pose_data, True)

        aim_position = Point(0.15, 0.25, 0.35)
        aim_orientation = Quaternion(0.0, 0.1, 0.0, 0.99)
        aim_pose_data = Pose(aim_position, aim_orientation)
        aim_pose = ControllerPose(aim_pose_data, True)

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

        # Create snapshot
        snapshot = ControllerSnapshot(grip_pose, aim_pose, inputs)

        # Verify all fields
        assert snapshot.grip_pose.is_valid is True
        assert snapshot.grip_pose.pose.position.x == pytest.approx(0.1)
        assert snapshot.aim_pose.is_valid is True
        assert snapshot.aim_pose.pose.position.x == pytest.approx(0.15)
        assert snapshot.inputs.primary_click is True
        assert snapshot.inputs.trigger_value == pytest.approx(1.0)

    def test_repr_with_default(self):
        """Test __repr__ with default values."""
        snapshot = ControllerSnapshot()
        repr_str = repr(snapshot)

        assert "ControllerSnapshot" in repr_str


class TestControllerIntegration:
    """Integration tests combining multiple controller types."""

    def test_left_and_right_different_states(self):
        """Test that left and right controllers can have different states."""
        # Create left controller (active)
        left_position = Point(-0.2, 0.0, 0.0)
        left_orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        left_pose_data = Pose(left_position, left_orientation)
        left_grip = ControllerPose(left_pose_data, True)
        left_aim = ControllerPose(left_pose_data, True)
        left_inputs = ControllerInputState(
            primary_click=True,
            secondary_click=False,
            thumbstick_click=False,
            thumbstick_x=0.0,
            thumbstick_y=0.0,
            squeeze_value=0.0,
            trigger_value=0.5,
        )
        left_snapshot = ControllerSnapshot(left_grip, left_aim, left_inputs)

        # Create right controller (default)
        right_snapshot = ControllerSnapshot()

        # Verify different states
        assert left_snapshot.inputs.trigger_value == pytest.approx(0.5)
        assert right_snapshot.inputs.trigger_value == pytest.approx(0.0)

    def test_default_controller(self):
        """Test representing a default-constructed controller."""
        snapshot = ControllerSnapshot()

        assert snapshot.grip_pose.is_valid is False
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
        controller_pose = ControllerPose(pose, False)

        assert controller_pose.is_valid is False
        # Pose data is still present even if not valid
        assert controller_pose.pose.position.x == pytest.approx(1.0)


class TestControllerSnapshotRecordTimestamp:
    """Tests for ControllerSnapshotRecord with DeviceDataTimestamp."""

    def test_construction_with_timestamp(self):
        """Test ControllerSnapshotRecord carries DeviceDataTimestamp."""
        grip = ControllerPose(
            Pose(Point(1.0, 0.0, 0.0), Quaternion(0.0, 0.0, 0.0, 1.0)), True
        )
        aim = ControllerPose(
            Pose(Point(0.0, 1.0, 0.0), Quaternion(0.0, 0.0, 0.0, 1.0)), True
        )
        inputs = ControllerInputState(True, False, False, 0.5, 0.0, 0.8, 1.0)
        data = ControllerSnapshot(grip, aim, inputs)
        ts = DeviceDataTimestamp(1000000000, 2000000000, 3000000000)
        record = ControllerSnapshotRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 1000000000
        assert record.timestamp.sample_time_local_common_clock == 2000000000
        assert record.timestamp.sample_time_raw_device_clock == 3000000000
        assert record.data is not None
        assert record.data.inputs.primary_click is True

    def test_default_construction(self):
        """Test default ControllerSnapshotRecord has no data."""
        record = ControllerSnapshotRecord()
        assert record.data is None

    def test_timestamp_fields(self):
        """Test all three DeviceDataTimestamp fields are accessible."""
        data = ControllerSnapshot()
        ts = DeviceDataTimestamp(111, 222, 333)
        record = ControllerSnapshotRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 111
        assert record.timestamp.sample_time_local_common_clock == 222
        assert record.timestamp.sample_time_raw_device_clock == 333
