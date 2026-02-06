# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Locomotion types in isaacteleop.schema.

Tests the following FlatBuffers types:
- Twist: Struct with linear and angular velocity (Point types)
- LocomotionCommand: Table with timestamp, velocity (Twist), and pose
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
    """Tests for LocomotionCommand table construction."""

    def test_default_construction(self):
        """Test default construction creates LocomotionCommand with None fields."""
        cmd = LocomotionCommand()

        assert cmd.timestamp is None
        assert cmd.velocity is None
        assert cmd.pose is None

    def test_repr(self):
        """Test __repr__ returns meaningful string."""
        cmd = LocomotionCommand()
        repr_str = repr(cmd)

        assert "LocomotionCommand" in repr_str


class TestLocomotionCommandTimestamp:
    """Tests for LocomotionCommand timestamp property."""

    def test_set_timestamp(self):
        """Test setting timestamp."""
        cmd = LocomotionCommand()
        timestamp = Timestamp(device_time=1000000000, common_time=2000000000)
        cmd.timestamp = timestamp

        assert cmd.timestamp is not None
        assert cmd.timestamp.device_time == 1000000000
        assert cmd.timestamp.common_time == 2000000000

    def test_large_timestamp_values(self):
        """Test with large int64 timestamp values."""
        cmd = LocomotionCommand()
        max_int64 = 9223372036854775807
        timestamp = Timestamp(device_time=max_int64, common_time=max_int64 - 1000)
        cmd.timestamp = timestamp

        assert cmd.timestamp.device_time == max_int64
        assert cmd.timestamp.common_time == max_int64 - 1000


class TestLocomotionCommandVelocity:
    """Tests for LocomotionCommand velocity property."""

    def test_set_velocity(self):
        """Test setting velocity."""
        cmd = LocomotionCommand()
        linear = Point(1.0, 0.0, 0.0)
        angular = Point(0.0, 0.0, 0.5)
        velocity = Twist(linear, angular)
        cmd.velocity = velocity

        assert cmd.velocity is not None
        assert cmd.velocity.linear.x == pytest.approx(1.0)
        assert cmd.velocity.angular.z == pytest.approx(0.5)

    def test_velocity_with_all_components(self):
        """Test velocity with all linear and angular components."""
        cmd = LocomotionCommand()
        linear = Point(1.0, 0.5, 0.1)
        angular = Point(0.1, 0.2, 0.3)
        velocity = Twist(linear, angular)
        cmd.velocity = velocity

        assert cmd.velocity.linear.x == pytest.approx(1.0)
        assert cmd.velocity.linear.y == pytest.approx(0.5)
        assert cmd.velocity.linear.z == pytest.approx(0.1)
        assert cmd.velocity.angular.x == pytest.approx(0.1)
        assert cmd.velocity.angular.y == pytest.approx(0.2)
        assert cmd.velocity.angular.z == pytest.approx(0.3)


class TestLocomotionCommandPose:
    """Tests for LocomotionCommand pose property."""

    def test_set_pose(self):
        """Test setting pose."""
        cmd = LocomotionCommand()
        position = Point(0.0, 0.0, -0.2)  # Squat down
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)  # Identity
        pose = Pose(position, orientation)
        cmd.pose = pose

        assert cmd.pose is not None
        assert cmd.pose.position.z == pytest.approx(-0.2)
        assert cmd.pose.orientation.w == pytest.approx(1.0)

    def test_pose_with_rotation(self):
        """Test pose with rotation quaternion."""
        cmd = LocomotionCommand()
        position = Point(0.0, 0.0, 0.0)
        # 90-degree rotation around Z axis
        orientation = Quaternion(0.0, 0.0, 0.7071068, 0.7071068)
        pose = Pose(position, orientation)
        cmd.pose = pose

        assert cmd.pose.orientation.z == pytest.approx(0.7071068, rel=1e-4)
        assert cmd.pose.orientation.w == pytest.approx(0.7071068, rel=1e-4)


class TestLocomotionCommandCombined:
    """Tests for LocomotionCommand with multiple fields set."""

    def test_velocity_only(self):
        """Test command with only velocity set (no pose)."""
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=1000, common_time=2000)
        cmd.velocity = Twist(Point(1.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))

        assert cmd.timestamp is not None
        assert cmd.velocity is not None
        assert cmd.pose is None

    def test_pose_only(self):
        """Test command with only pose set (no velocity)."""
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=3000, common_time=4000)
        cmd.pose = Pose(Point(0.0, 0.0, -0.1), Quaternion(0.0, 0.0, 0.0, 1.0))

        assert cmd.timestamp is not None
        assert cmd.velocity is None
        assert cmd.pose is not None

    def test_both_velocity_and_pose(self):
        """Test command with both velocity and pose set."""
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=5000, common_time=6000)
        cmd.velocity = Twist(Point(0.5, 0.0, 0.0), Point(0.0, 0.0, 0.1))
        cmd.pose = Pose(Point(0.0, 0.0, 0.05), Quaternion(0.0, 0.0, 0.0, 1.0))

        assert cmd.timestamp is not None
        assert cmd.velocity is not None
        assert cmd.pose is not None
        assert cmd.velocity.linear.x == pytest.approx(0.5)
        assert cmd.pose.position.z == pytest.approx(0.05)


class TestLocomotionCommandFootPedalScenarios:
    """Tests for realistic foot pedal input scenarios."""

    def test_forward_motion(self):
        """Test typical forward motion command from foot pedal."""
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=1000000, common_time=1000000)
        # Forward velocity from foot pedal
        cmd.velocity = Twist(Point(0.5, 0.0, 0.0), Point(0.0, 0.0, 0.0))

        assert cmd.velocity.linear.x == pytest.approx(0.5)
        assert cmd.velocity.linear.y == pytest.approx(0.0)
        assert cmd.velocity.angular.z == pytest.approx(0.0)

    def test_turning_motion(self):
        """Test turning motion command from foot pedal."""
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=2000000, common_time=2000000)
        # Forward + turning
        cmd.velocity = Twist(Point(0.3, 0.0, 0.0), Point(0.0, 0.0, 0.5))

        assert cmd.velocity.linear.x == pytest.approx(0.3)
        assert cmd.velocity.angular.z == pytest.approx(0.5)

    def test_squat_mode(self):
        """Test squat mode command (vertical mode) from foot pedal."""
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=3000000, common_time=3000000)
        # Squat down pose
        cmd.pose = Pose(Point(0.0, 0.0, -0.15), Quaternion(0.0, 0.0, 0.0, 1.0))

        assert cmd.pose.position.z == pytest.approx(-0.15)

    def test_stationary(self):
        """Test stationary command (zero velocity)."""
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=4000000, common_time=4000000)
        cmd.velocity = Twist(Point(0.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))

        assert cmd.velocity.linear.x == pytest.approx(0.0)
        assert cmd.velocity.linear.y == pytest.approx(0.0)
        assert cmd.velocity.angular.z == pytest.approx(0.0)


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
        twist = Twist(Point(max_vel, max_vel, max_vel), Point(max_vel, max_vel, max_vel))

        assert twist.linear.x == pytest.approx(max_vel)
        assert twist.angular.z == pytest.approx(max_vel)


class TestLocomotionCommandEdgeCases:
    """Edge case tests for LocomotionCommand table."""

    def test_zero_timestamp(self):
        """Test with zero timestamp values."""
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=0, common_time=0)

        assert cmd.timestamp.device_time == 0
        assert cmd.timestamp.common_time == 0

    def test_negative_timestamp(self):
        """Test with negative timestamp values (valid for relative times)."""
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=-1000, common_time=-2000)

        assert cmd.timestamp.device_time == -1000
        assert cmd.timestamp.common_time == -2000

    def test_overwrite_velocity(self):
        """Test overwriting velocity field."""
        cmd = LocomotionCommand()
        cmd.velocity = Twist(Point(1.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        cmd.velocity = Twist(Point(2.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))

        assert cmd.velocity.linear.x == pytest.approx(2.0)

    def test_overwrite_pose(self):
        """Test overwriting pose field."""
        cmd = LocomotionCommand()
        cmd.pose = Pose(Point(0.0, 0.0, -0.1), Quaternion(0.0, 0.0, 0.0, 1.0))
        cmd.pose = Pose(Point(0.0, 0.0, -0.2), Quaternion(0.0, 0.0, 0.0, 1.0))

        assert cmd.pose.position.z == pytest.approx(-0.2)
