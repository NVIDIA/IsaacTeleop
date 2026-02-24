# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Locomotion types in isaacteleop.schema.

Tests the following FlatBuffers types:
- Twist: Struct with linear and angular velocity (Point types)
- LocomotionCommand: Struct (read-only) with timestamp, velocity (Twist), and pose
"""

import pytest

from isaacteleop.schema import (
    Twist,
    LocomotionCommand,
    Point,
    Pose,
    Quaternion,
    Timestamp,
)


class TestTwistConstruction:
    """Tests for Twist struct construction."""

    def test_default_construction(self):
        """Test default construction creates Twist with zero values."""
        twist = Twist()

        assert twist.linear.x == 0.0
        assert twist.linear.y == 0.0
        assert twist.linear.z == 0.0
        assert twist.angular.x == 0.0
        assert twist.angular.y == 0.0
        assert twist.angular.z == 0.0

    def test_construction_with_values(self):
        """Test construction with linear and angular velocity values."""
        linear = Point(1.0, 2.0, 0.0)
        angular = Point(0.0, 0.0, 0.5)
        twist = Twist(linear, angular)

        assert twist.linear.x == pytest.approx(1.0)
        assert twist.linear.y == pytest.approx(2.0)
        assert twist.linear.z == pytest.approx(0.0)
        assert twist.angular.x == pytest.approx(0.0)
        assert twist.angular.y == pytest.approx(0.0)
        assert twist.angular.z == pytest.approx(0.5)


class TestTwistLinearVelocity:
    """Tests for Twist linear velocity access."""

    def test_forward_velocity(self):
        """Test forward velocity (positive x)."""
        linear = Point(1.5, 0.0, 0.0)
        angular = Point(0.0, 0.0, 0.0)
        twist = Twist(linear, angular)

        assert twist.linear.x == pytest.approx(1.5)
        assert twist.linear.y == pytest.approx(0.0)

    def test_backward_velocity(self):
        """Test backward velocity (negative x)."""
        linear = Point(-1.0, 0.0, 0.0)
        angular = Point(0.0, 0.0, 0.0)
        twist = Twist(linear, angular)

        assert twist.linear.x == pytest.approx(-1.0)

    def test_lateral_velocity(self):
        """Test lateral (sideways) velocity."""
        linear = Point(0.0, 0.5, 0.0)
        angular = Point(0.0, 0.0, 0.0)
        twist = Twist(linear, angular)

        assert twist.linear.y == pytest.approx(0.5)

    def test_combined_linear_velocity(self):
        """Test combined forward and lateral velocity."""
        linear = Point(1.0, 0.5, 0.0)
        angular = Point(0.0, 0.0, 0.0)
        twist = Twist(linear, angular)

        assert twist.linear.x == pytest.approx(1.0)
        assert twist.linear.y == pytest.approx(0.5)


class TestTwistAngularVelocity:
    """Tests for Twist angular velocity access."""

    def test_yaw_rotation(self):
        """Test yaw rotation (rotation around z-axis)."""
        linear = Point(0.0, 0.0, 0.0)
        angular = Point(0.0, 0.0, 0.5)
        twist = Twist(linear, angular)

        assert twist.angular.z == pytest.approx(0.5)

    def test_negative_yaw_rotation(self):
        """Test negative yaw rotation."""
        linear = Point(0.0, 0.0, 0.0)
        angular = Point(0.0, 0.0, -0.3)
        twist = Twist(linear, angular)

        assert twist.angular.z == pytest.approx(-0.3)

    def test_pitch_rotation(self):
        """Test pitch rotation (rotation around y-axis)."""
        linear = Point(0.0, 0.0, 0.0)
        angular = Point(0.0, 0.2, 0.0)
        twist = Twist(linear, angular)

        assert twist.angular.y == pytest.approx(0.2)

    def test_roll_rotation(self):
        """Test roll rotation (rotation around x-axis)."""
        linear = Point(0.0, 0.0, 0.0)
        angular = Point(0.1, 0.0, 0.0)
        twist = Twist(linear, angular)

        assert twist.angular.x == pytest.approx(0.1)


class TestTwistRepr:
    """Tests for Twist __repr__ method."""

    def test_repr(self):
        """Test __repr__ returns meaningful string."""
        linear = Point(1.0, 2.0, 0.0)
        angular = Point(0.0, 0.0, 0.5)
        twist = Twist(linear, angular)

        repr_str = repr(twist)
        assert "Twist" in repr_str
        assert "linear" in repr_str
        assert "angular" in repr_str


class TestLocomotionCommandConstruction:
    """Tests for LocomotionCommand struct construction."""

    def test_default_construction(self):
        """Test default construction creates LocomotionCommand with zero-initialized fields."""
        cmd = LocomotionCommand()

        assert cmd.timestamp.device_time == 0
        assert cmd.velocity.linear.x == 0.0
        assert cmd.pose.position.x == 0.0

    def test_repr(self):
        """Test __repr__ returns meaningful string."""
        cmd = LocomotionCommand()
        repr_str = repr(cmd)

        assert "LocomotionCommand" in repr_str


class TestTwistEdgeCases:
    """Edge case tests for Twist struct."""

    def test_zero_velocities(self):
        """Test with all zero velocities."""
        twist = Twist(Point(0.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))

        assert twist.linear.x == 0.0
        assert twist.linear.y == 0.0
        assert twist.linear.z == 0.0
        assert twist.angular.x == 0.0
        assert twist.angular.y == 0.0
        assert twist.angular.z == 0.0

    def test_negative_velocities(self):
        """Test with negative velocities."""
        twist = Twist(Point(-1.0, -0.5, -0.1), Point(-0.1, -0.2, -0.3))

        assert twist.linear.x == pytest.approx(-1.0)
        assert twist.linear.y == pytest.approx(-0.5)
        assert twist.angular.z == pytest.approx(-0.3)

    def test_max_velocities(self):
        """Test with maximum reasonable velocities."""
        max_vel = 10.0  # Reasonable max velocity for robot
        twist = Twist(
            Point(max_vel, max_vel, max_vel), Point(max_vel, max_vel, max_vel)
        )

        assert twist.linear.x == pytest.approx(max_vel)
        assert twist.angular.z == pytest.approx(max_vel)
