# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Pose struct in isaacteleop.schema.

Note: Pose is now a FlatBuffers struct (not a table), which means:
- It's a fixed-size, inline type
- It contains Point (x, y, z) and Quaternion (x, y, z, w) directly
- No nullable fields - all values are always present
"""

import pytest

from isaacteleop.schema import Pose, Point, Quaternion


class TestPoseConstruction:
    """Tests for Pose struct construction."""

    def test_constructor_with_values(self):
        """Test construction with position and orientation values."""
        position = Point(1.5, 2.5, 3.5)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)  # Identity quaternion (x, y, z, w)
        pose = Pose(position, orientation)

        assert pose is not None

    def test_default_constructor(self):
        """Test default construction creates pose with zero values."""
        pose = Pose()

        assert pose.position.x == 0.0
        assert pose.position.y == 0.0
        assert pose.position.z == 0.0
        assert pose.orientation.x == 0.0
        assert pose.orientation.y == 0.0
        assert pose.orientation.z == 0.0
        assert pose.orientation.w == 0.0


class TestPosePositionAccess:
    """Tests for Pose position property access."""

    def test_position_values(self):
        """Test accessing position values."""
        position = Point(1.5, 2.5, 3.5)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        pose = Pose(position, orientation)

        assert pose.position.x == pytest.approx(1.5)
        assert pose.position.y == pytest.approx(2.5)
        assert pose.position.z == pytest.approx(3.5)

    def test_negative_position_values(self):
        """Test accessing negative position values."""
        position = Point(-1.0, -2.0, -3.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        pose = Pose(position, orientation)

        assert pose.position.x == pytest.approx(-1.0)
        assert pose.position.y == pytest.approx(-2.0)
        assert pose.position.z == pytest.approx(-3.0)


class TestPoseOrientationAccess:
    """Tests for Pose orientation property access."""

    def test_identity_quaternion(self):
        """Test accessing identity quaternion orientation."""
        position = Point(0.0, 0.0, 0.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)  # Identity (x, y, z, w)
        pose = Pose(position, orientation)

        assert pose.orientation.x == pytest.approx(0.0)
        assert pose.orientation.y == pytest.approx(0.0)
        assert pose.orientation.z == pytest.approx(0.0)
        assert pose.orientation.w == pytest.approx(1.0)

    def test_rotation_quaternion(self):
        """Test 90-degree rotation around Z axis."""
        position = Point(0.0, 0.0, 0.0)
        # 90-degree rotation around Z axis: x=0, y=0, z=0.7071, w=0.7071
        orientation = Quaternion(0.0, 0.0, 0.7071068, 0.7071068)
        pose = Pose(position, orientation)

        assert pose.orientation.x == pytest.approx(0.0)
        assert pose.orientation.y == pytest.approx(0.0)
        assert pose.orientation.z == pytest.approx(0.7071068, rel=1e-4)
        assert pose.orientation.w == pytest.approx(0.7071068, rel=1e-4)


class TestPointStruct:
    """Tests for Point struct."""

    def test_point_construction(self):
        """Test Point struct construction."""
        point = Point(1.0, 2.0, 3.0)

        assert point.x == pytest.approx(1.0)
        assert point.y == pytest.approx(2.0)
        assert point.z == pytest.approx(3.0)

    def test_point_default_construction(self):
        """Test Point default construction."""
        point = Point()

        assert point.x == 0.0
        assert point.y == 0.0
        assert point.z == 0.0


class TestQuaternionStruct:
    """Tests for Quaternion struct."""

    def test_quaternion_construction(self):
        """Test Quaternion struct construction (x, y, z, w order)."""
        quat = Quaternion(0.1, 0.2, 0.3, 0.9)

        assert quat.x == pytest.approx(0.1)
        assert quat.y == pytest.approx(0.2)
        assert quat.z == pytest.approx(0.3)
        assert quat.w == pytest.approx(0.9)

    def test_quaternion_default_construction(self):
        """Test Quaternion default construction."""
        quat = Quaternion()

        assert quat.x == 0.0
        assert quat.y == 0.0
        assert quat.z == 0.0
        assert quat.w == 0.0

    def test_identity_quaternion(self):
        """Test creating identity quaternion."""
        quat = Quaternion(0.0, 0.0, 0.0, 1.0)

        assert quat.x == 0.0
        assert quat.y == 0.0
        assert quat.z == 0.0
        assert quat.w == 1.0


class TestPoseFullPose:
    """Tests for Pose with both position and orientation."""

    def test_full_pose(self):
        """Test creating pose with both position and orientation."""
        position = Point(1.0, 2.0, 3.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        pose = Pose(position, orientation)

        # Verify position
        assert pose.position.x == pytest.approx(1.0)
        assert pose.position.y == pytest.approx(2.0)
        assert pose.position.z == pytest.approx(3.0)

        # Verify orientation
        assert pose.orientation.x == pytest.approx(0.0)
        assert pose.orientation.y == pytest.approx(0.0)
        assert pose.orientation.z == pytest.approx(0.0)
        assert pose.orientation.w == pytest.approx(1.0)


class TestPoseDataTypes:
    """Tests for Pose with various input types."""

    def test_float_inputs(self):
        """Test pose with Python float inputs."""
        position = Point(1.0, 2.0, 3.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        pose = Pose(position, orientation)

        assert isinstance(pose.position.x, float)
        assert isinstance(pose.orientation.w, float)

    def test_int_inputs_converted_to_float(self):
        """Test pose with int inputs (should be converted to float)."""
        position = Point(1, 2, 3)
        orientation = Quaternion(0, 0, 0, 1)
        pose = Pose(position, orientation)

        assert pose.position.x == pytest.approx(1.0)
        assert pose.position.y == pytest.approx(2.0)
        assert pose.position.z == pytest.approx(3.0)
        assert pose.orientation.w == pytest.approx(1.0)
