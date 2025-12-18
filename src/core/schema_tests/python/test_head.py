# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for HeadPoseT in teleopcore.schema.

HeadPoseT is a FlatBuffers table (mutable object-API) that represents head pose data,
including:
- pose: The concrete Pose data (position and orientation)
- is_valid: Whether the head pose data is valid
- timestamp: The timestamp in XrTime format (int64)
"""

import pytest

from teleopcore.schema import HeadPoseT, Pose, Point, Quaternion


class TestHeadPoseTConstruction:
    """Tests for HeadPoseT construction."""

    def test_default_construction(self):
        """Test default construction creates HeadPoseT with default values."""
        head_pose = HeadPoseT()

        assert head_pose is not None
        assert head_pose.pose is None
        assert head_pose.is_valid is False
        assert head_pose.timestamp == 0

    def test_is_valid_can_be_set(self):
        """Test that is_valid can be set to True."""
        head_pose = HeadPoseT()
        head_pose.is_valid = True

        assert head_pose.is_valid is True

    def test_timestamp_can_be_set(self):
        """Test that timestamp can be set."""
        head_pose = HeadPoseT()
        head_pose.timestamp = 1234567890123456789

        assert head_pose.timestamp == 1234567890123456789


class TestHeadPoseTPose:
    """Tests for HeadPoseT pose property."""

    def test_set_pose_convenience_method(self):
        """Test setting pose using the convenience method."""
        head_pose = HeadPoseT()
        position = Point(1.5, 2.5, 3.5)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)

        head_pose.set_pose(position, orientation)

        assert head_pose.pose is not None
        assert head_pose.pose.position.x == pytest.approx(1.5)
        assert head_pose.pose.position.y == pytest.approx(2.5)
        assert head_pose.pose.position.z == pytest.approx(3.5)
        assert head_pose.pose.orientation.x == pytest.approx(0.0)
        assert head_pose.pose.orientation.y == pytest.approx(0.0)
        assert head_pose.pose.orientation.z == pytest.approx(0.0)
        assert head_pose.pose.orientation.w == pytest.approx(1.0)

    def test_set_pose_with_rotation(self):
        """Test setting pose with a rotation quaternion."""
        head_pose = HeadPoseT()
        position = Point(0.0, 0.0, 0.0)
        # 90-degree rotation around Z axis
        orientation = Quaternion(0.0, 0.0, 0.7071068, 0.7071068)

        head_pose.set_pose(position, orientation)

        assert head_pose.pose.orientation.z == pytest.approx(0.7071068, rel=1e-4)
        assert head_pose.pose.orientation.w == pytest.approx(0.7071068, rel=1e-4)


class TestHeadPoseTFullUsage:
    """Tests for HeadPoseT with all fields set."""

    def test_full_head_pose_data(self):
        """Test creating a complete HeadPoseT with all fields."""
        head_pose = HeadPoseT()

        # Set pose.
        position = Point(1.0, 2.0, 3.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        head_pose.set_pose(position, orientation)

        # Set validity.
        head_pose.is_valid = True

        # Set timestamp.
        head_pose.timestamp = 9876543210

        # Verify all fields.
        assert head_pose.pose is not None
        assert head_pose.pose.position.x == pytest.approx(1.0)
        assert head_pose.pose.position.y == pytest.approx(2.0)
        assert head_pose.pose.position.z == pytest.approx(3.0)
        assert head_pose.is_valid is True
        assert head_pose.timestamp == 9876543210

    def test_negative_position_values(self):
        """Test HeadPoseT with negative position values."""
        head_pose = HeadPoseT()
        position = Point(-1.0, -2.0, -3.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)

        head_pose.set_pose(position, orientation)

        assert head_pose.pose.position.x == pytest.approx(-1.0)
        assert head_pose.pose.position.y == pytest.approx(-2.0)
        assert head_pose.pose.position.z == pytest.approx(-3.0)


class TestHeadPoseTRepr:
    """Tests for HeadPoseT __repr__ method."""

    def test_repr_with_no_pose(self):
        """Test __repr__ when pose is not set."""
        head_pose = HeadPoseT()
        repr_str = repr(head_pose)

        assert "HeadPoseT" in repr_str
        assert "None" in repr_str
        assert "is_valid=False" in repr_str

    def test_repr_with_pose(self):
        """Test __repr__ when pose is set."""
        head_pose = HeadPoseT()
        head_pose.set_pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        head_pose.is_valid = True

        repr_str = repr(head_pose)

        assert "HeadPoseT" in repr_str
        assert "Pose" in repr_str
        assert "is_valid=True" in repr_str


class TestHeadPoseTDataTypes:
    """Tests for HeadPoseT with various input types."""

    def test_int_inputs_converted_to_float(self):
        """Test HeadPoseT with int inputs (should be converted to float)."""
        head_pose = HeadPoseT()
        position = Point(1, 2, 3)
        orientation = Quaternion(0, 0, 0, 1)

        head_pose.set_pose(position, orientation)

        assert head_pose.pose.position.x == pytest.approx(1.0)
        assert head_pose.pose.position.y == pytest.approx(2.0)
        assert head_pose.pose.position.z == pytest.approx(3.0)

    def test_large_timestamp(self):
        """Test HeadPoseT with a large timestamp value (int64 range)."""
        head_pose = HeadPoseT()
        large_timestamp = 9223372036854775807  # Max int64

        head_pose.timestamp = large_timestamp

        assert head_pose.timestamp == large_timestamp

    def test_negative_timestamp(self):
        """Test HeadPoseT with a negative timestamp value."""
        head_pose = HeadPoseT()
        negative_timestamp = -1234567890

        head_pose.timestamp = negative_timestamp

        assert head_pose.timestamp == negative_timestamp

