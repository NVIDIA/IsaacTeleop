# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Locomotion types in isaacteleop.schema.

Tests the following FlatBuffers types:
- Twist: Struct with linear and angular velocity (Point types)
- LocomotionCommand: Table with timestamp, velocity (Twist), pose, velocity_valid, pose_valid
- LocomotionCommandTrackedT: Tracked wrapper (data is None when inactive)

velocity_valid and pose_valid flags indicate the active mode. Both velocity and pose are
always populated when data is non-null; only consume the field whose valid flag is True.
"""

import pytest

from isaacteleop.schema import (
    LocomotionCommand,
    LocomotionCommandTrackedT,
    Point,
    Pose,
    Quaternion,
    Timestamp,
    Twist,
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
        twist = Twist(Point(1.5, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        assert twist.linear.x == pytest.approx(1.5)
        assert twist.linear.y == pytest.approx(0.0)

    def test_backward_velocity(self):
        """Test backward velocity (negative x)."""
        twist = Twist(Point(-1.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        assert twist.linear.x == pytest.approx(-1.0)

    def test_lateral_velocity(self):
        """Test lateral (sideways) velocity."""
        twist = Twist(Point(0.0, 0.5, 0.0), Point(0.0, 0.0, 0.0))
        assert twist.linear.y == pytest.approx(0.5)

    def test_combined_linear_velocity(self):
        """Test combined forward and lateral velocity."""
        twist = Twist(Point(1.0, 0.5, 0.0), Point(0.0, 0.0, 0.0))
        assert twist.linear.x == pytest.approx(1.0)
        assert twist.linear.y == pytest.approx(0.5)


class TestTwistAngularVelocity:
    """Tests for Twist angular velocity access."""

    def test_yaw_rotation(self):
        twist = Twist(Point(0.0, 0.0, 0.0), Point(0.0, 0.0, 0.5))
        assert twist.angular.z == pytest.approx(0.5)

    def test_negative_yaw_rotation(self):
        twist = Twist(Point(0.0, 0.0, 0.0), Point(0.0, 0.0, -0.3))
        assert twist.angular.z == pytest.approx(-0.3)

    def test_pitch_rotation(self):
        twist = Twist(Point(0.0, 0.0, 0.0), Point(0.0, 0.2, 0.0))
        assert twist.angular.y == pytest.approx(0.2)

    def test_roll_rotation(self):
        twist = Twist(Point(0.0, 0.0, 0.0), Point(0.1, 0.0, 0.0))
        assert twist.angular.x == pytest.approx(0.1)


class TestTwistRepr:
    def test_repr(self):
        twist = Twist(Point(1.0, 2.0, 0.0), Point(0.0, 0.0, 0.5))
        repr_str = repr(twist)
        assert "Twist" in repr_str
        assert "linear" in repr_str
        assert "angular" in repr_str


class TestLocomotionCommandConstruction:
    """Tests for LocomotionCommand table construction."""

    def test_default_construction(self):
        """Default construction initializes all fields; validity flags default to False."""
        cmd = LocomotionCommand()

        assert cmd.timestamp is not None
        assert cmd.velocity is not None
        assert cmd.pose is not None
        assert cmd.velocity_valid is False
        assert cmd.pose_valid is False

    def test_repr(self):
        cmd = LocomotionCommand()
        repr_str = repr(cmd)
        assert "LocomotionCommand" in repr_str
        assert "velocity_valid" in repr_str
        assert "pose_valid" in repr_str


class TestLocomotionCommandValidityFlags:
    """Tests for velocity_valid and pose_valid flags."""

    def test_velocity_mode(self):
        """Velocity mode: velocity_valid=True, pose_valid=False."""
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=1000, common_time=2000)
        cmd.velocity = Twist(Point(1.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        cmd.velocity_valid = True
        cmd.pose = Pose(Point(0.0, 0.0, 0.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        cmd.pose_valid = False

        assert cmd.velocity_valid is True
        assert cmd.pose_valid is False
        assert cmd.velocity.linear.x == pytest.approx(1.0)

    def test_pose_mode(self):
        """Pose mode: pose_valid=True, velocity_valid=False."""
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=3000, common_time=4000)
        cmd.velocity = Twist(Point(0.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        cmd.velocity_valid = False
        cmd.pose = Pose(Point(0.0, 0.0, -0.1), Quaternion(0.0, 0.0, 0.0, 1.0))
        cmd.pose_valid = True

        assert cmd.velocity_valid is False
        assert cmd.pose_valid is True
        assert cmd.pose.position.z == pytest.approx(-0.1)

    def test_set_velocity_valid_flag(self):
        """Test toggling velocity_valid."""
        cmd = LocomotionCommand()
        assert cmd.velocity_valid is False
        cmd.velocity_valid = True
        assert cmd.velocity_valid is True

    def test_set_pose_valid_flag(self):
        """Test toggling pose_valid."""
        cmd = LocomotionCommand()
        assert cmd.pose_valid is False
        cmd.pose_valid = True
        assert cmd.pose_valid is True


class TestLocomotionCommandTimestamp:
    """Tests for LocomotionCommand timestamp property."""

    def test_set_timestamp(self):
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=1000000000, common_time=2000000000)
        assert cmd.timestamp.device_time == 1000000000
        assert cmd.timestamp.common_time == 2000000000

    def test_large_timestamp_values(self):
        cmd = LocomotionCommand()
        max_int64 = 9223372036854775807
        cmd.timestamp = Timestamp(device_time=max_int64, common_time=max_int64 - 1000)
        assert cmd.timestamp.device_time == max_int64
        assert cmd.timestamp.common_time == max_int64 - 1000


class TestLocomotionCommandVelocity:
    """Tests for LocomotionCommand velocity property."""

    def test_set_velocity(self):
        cmd = LocomotionCommand()
        cmd.velocity = Twist(Point(1.0, 0.0, 0.0), Point(0.0, 0.0, 0.5))
        assert cmd.velocity.linear.x == pytest.approx(1.0)
        assert cmd.velocity.angular.z == pytest.approx(0.5)

    def test_velocity_with_all_components(self):
        cmd = LocomotionCommand()
        cmd.velocity = Twist(Point(1.0, 0.5, 0.1), Point(0.1, 0.2, 0.3))
        assert cmd.velocity.linear.x == pytest.approx(1.0)
        assert cmd.velocity.linear.y == pytest.approx(0.5)
        assert cmd.velocity.linear.z == pytest.approx(0.1)
        assert cmd.velocity.angular.x == pytest.approx(0.1)
        assert cmd.velocity.angular.y == pytest.approx(0.2)
        assert cmd.velocity.angular.z == pytest.approx(0.3)


class TestLocomotionCommandPose:
    """Tests for LocomotionCommand pose property."""

    def test_set_pose(self):
        cmd = LocomotionCommand()
        cmd.pose = Pose(Point(0.0, 0.0, -0.2), Quaternion(0.0, 0.0, 0.0, 1.0))
        assert cmd.pose.position.z == pytest.approx(-0.2)
        assert cmd.pose.orientation.w == pytest.approx(1.0)

    def test_pose_with_rotation(self):
        cmd = LocomotionCommand()
        cmd.pose = Pose(
            Point(0.0, 0.0, 0.0), Quaternion(0.0, 0.0, 0.7071068, 0.7071068)
        )
        assert cmd.pose.orientation.z == pytest.approx(0.7071068, rel=1e-4)
        assert cmd.pose.orientation.w == pytest.approx(0.7071068, rel=1e-4)


class TestLocomotionCommandParametrizedConstructor:
    """Tests for the parametrized LocomotionCommand constructor."""

    def test_velocity_mode_constructor(self):
        velocity = Twist(Point(1.0, 0.0, 0.0), Point(0.0, 0.0, 0.5))
        pose = Pose(Point(0.0, 0.0, 0.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        ts = Timestamp(device_time=1000, common_time=2000)
        cmd = LocomotionCommand(velocity, True, pose, False, ts)

        assert cmd.velocity_valid is True
        assert cmd.pose_valid is False
        assert cmd.velocity.linear.x == pytest.approx(1.0)
        assert cmd.timestamp.device_time == 1000

    def test_pose_mode_constructor(self):
        velocity = Twist(Point(0.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        pose = Pose(Point(0.0, 0.0, -0.15), Quaternion(0.0, 0.0, 0.0, 1.0))
        ts = Timestamp(device_time=3000, common_time=4000)
        cmd = LocomotionCommand(velocity, False, pose, True, ts)

        assert cmd.velocity_valid is False
        assert cmd.pose_valid is True
        assert cmd.pose.position.z == pytest.approx(-0.15)


class TestLocomotionCommandTrackedT:
    """Tests for LocomotionCommandTrackedT wrapper."""

    def test_default_construction_inactive(self):
        tracked = LocomotionCommandTrackedT()
        assert tracked.data is None

    def test_construction_with_data(self):
        cmd = LocomotionCommand()
        cmd.velocity = Twist(Point(1.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        cmd.velocity_valid = True
        tracked = LocomotionCommandTrackedT(cmd)

        assert tracked.data is not None
        assert tracked.data.velocity_valid is True

    def test_repr_inactive(self):
        tracked = LocomotionCommandTrackedT()
        assert "None" in repr(tracked)

    def test_repr_active(self):
        cmd = LocomotionCommand()
        tracked = LocomotionCommandTrackedT(cmd)
        assert "LocomotionCommand" in repr(tracked)


class TestLocomotionCommandFootPedalScenarios:
    """Tests for realistic foot pedal input scenarios."""

    def test_forward_motion(self):
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=1000000, common_time=1000000)
        cmd.velocity = Twist(Point(0.5, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        cmd.velocity_valid = True
        cmd.pose = Pose(Point(0.0, 0.0, 0.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        cmd.pose_valid = False

        assert cmd.velocity_valid is True
        assert cmd.velocity.linear.x == pytest.approx(0.5)
        assert cmd.velocity.linear.y == pytest.approx(0.0)
        assert cmd.velocity.angular.z == pytest.approx(0.0)

    def test_turning_motion(self):
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=2000000, common_time=2000000)
        cmd.velocity = Twist(Point(0.3, 0.0, 0.0), Point(0.0, 0.0, 0.5))
        cmd.velocity_valid = True
        cmd.pose = Pose(Point(0.0, 0.0, 0.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        cmd.pose_valid = False

        assert cmd.velocity_valid is True
        assert cmd.velocity.linear.x == pytest.approx(0.3)
        assert cmd.velocity.angular.z == pytest.approx(0.5)

    def test_squat_mode(self):
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=3000000, common_time=3000000)
        cmd.velocity = Twist(Point(0.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        cmd.velocity_valid = False
        cmd.pose = Pose(Point(0.0, 0.0, -0.15), Quaternion(0.0, 0.0, 0.0, 1.0))
        cmd.pose_valid = True

        assert cmd.pose_valid is True
        assert cmd.pose.position.z == pytest.approx(-0.15)

    def test_stationary(self):
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=4000000, common_time=4000000)
        cmd.velocity = Twist(Point(0.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        cmd.velocity_valid = True
        cmd.pose = Pose(Point(0.0, 0.0, 0.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        cmd.pose_valid = False

        assert cmd.velocity_valid is True
        assert cmd.velocity.linear.x == pytest.approx(0.0)
        assert cmd.velocity.linear.y == pytest.approx(0.0)
        assert cmd.velocity.angular.z == pytest.approx(0.0)


class TestTwistEdgeCases:
    def test_zero_velocities(self):
        twist = Twist(Point(0.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        assert twist.linear.x == 0.0
        assert twist.angular.z == 0.0

    def test_negative_velocities(self):
        twist = Twist(Point(-1.0, -0.5, -0.1), Point(-0.1, -0.2, -0.3))
        assert twist.linear.x == pytest.approx(-1.0)
        assert twist.linear.y == pytest.approx(-0.5)
        assert twist.angular.z == pytest.approx(-0.3)

    def test_max_velocities(self):
        max_vel = 10.0
        twist = Twist(
            Point(max_vel, max_vel, max_vel), Point(max_vel, max_vel, max_vel)
        )
        assert twist.linear.x == pytest.approx(max_vel)
        assert twist.angular.z == pytest.approx(max_vel)


class TestLocomotionCommandEdgeCases:
    def test_zero_timestamp(self):
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=0, common_time=0)
        assert cmd.timestamp.device_time == 0
        assert cmd.timestamp.common_time == 0

    def test_negative_timestamp(self):
        cmd = LocomotionCommand()
        cmd.timestamp = Timestamp(device_time=-1000, common_time=-2000)
        assert cmd.timestamp.device_time == -1000
        assert cmd.timestamp.common_time == -2000

    def test_overwrite_velocity(self):
        cmd = LocomotionCommand()
        cmd.velocity = Twist(Point(1.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        cmd.velocity = Twist(Point(2.0, 0.0, 0.0), Point(0.0, 0.0, 0.0))
        assert cmd.velocity.linear.x == pytest.approx(2.0)

    def test_overwrite_pose(self):
        cmd = LocomotionCommand()
        cmd.pose = Pose(Point(0.0, 0.0, -0.1), Quaternion(0.0, 0.0, 0.0, 1.0))
        cmd.pose = Pose(Point(0.0, 0.0, -0.2), Quaternion(0.0, 0.0, 0.0, 1.0))
        assert cmd.pose.position.z == pytest.approx(-0.2)

    def test_overwrite_validity_flags(self):
        cmd = LocomotionCommand()
        cmd.velocity_valid = True
        cmd.pose_valid = False
        cmd.velocity_valid = False
        cmd.pose_valid = True
        assert cmd.velocity_valid is False
        assert cmd.pose_valid is True
