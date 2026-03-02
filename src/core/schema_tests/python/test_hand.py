# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for HandPoseT and related types in isaacteleop.schema.

HandPoseT is a FlatBuffers table that represents hand pose data:
- joints: HandJoints struct containing 26 HandJointPose entries (XR_HAND_JOINT_COUNT_EXT)

HandJoints is a struct with a fixed-size array of 26 HandJointPose entries.

HandJointPose is a struct containing:
- pose: The Pose (position and orientation)
- is_valid: Whether this joint data is valid
- radius: The radius of the joint (from OpenXR)

Timestamps are carried by HandPoseRecord, not HandPoseT.
"""

import pytest

from isaacteleop.schema import (
    HandPoseT,
    HandPoseRecord,
    HandJoints,
    HandJointPose,
    Pose,
    Point,
    Quaternion,
    DeviceDataTimestamp,
)


class TestHandJointPoseConstruction:
    """Tests for HandJointPose construction."""

    def test_default_construction(self):
        """Test default construction creates HandJointPose with default values."""
        joint_pose = HandJointPose()

        assert joint_pose is not None
        # Default pose values should be zero.
        assert joint_pose.pose.position.x == 0.0
        assert joint_pose.pose.position.y == 0.0
        assert joint_pose.pose.position.z == 0.0
        assert joint_pose.is_valid is False
        assert joint_pose.radius == 0.0

    def test_construction_with_values(self):
        """Test construction with position, orientation, is_valid, and radius."""
        position = Point(1.0, 2.0, 3.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        pose = Pose(position, orientation)
        joint_pose = HandJointPose(pose, True, 0.01)

        assert joint_pose.pose.position.x == pytest.approx(1.0)
        assert joint_pose.pose.position.y == pytest.approx(2.0)
        assert joint_pose.pose.position.z == pytest.approx(3.0)
        assert joint_pose.is_valid is True
        assert joint_pose.radius == pytest.approx(0.01)


class TestHandJointPoseAccess:
    """Tests for HandJointPose property access."""

    def test_pose_access(self):
        """Test accessing pose property."""
        position = Point(1.5, 2.5, 3.5)
        orientation = Quaternion(0.1, 0.2, 0.3, 0.9)
        pose = Pose(position, orientation)
        joint_pose = HandJointPose(pose, True, 0.015)

        assert joint_pose.pose.position.x == pytest.approx(1.5)
        assert joint_pose.pose.orientation.w == pytest.approx(0.9)

    def test_is_valid_access(self):
        """Test accessing is_valid property."""
        pose = Pose(Point(), Quaternion())
        joint_pose = HandJointPose(pose, True, 0.0)

        assert joint_pose.is_valid is True

    def test_radius_access(self):
        """Test accessing radius property."""
        pose = Pose(Point(), Quaternion())
        joint_pose = HandJointPose(pose, False, 0.025)

        assert joint_pose.radius == pytest.approx(0.025)


class TestHandJointPoseRepr:
    """Tests for HandJointPose __repr__ method."""

    def test_repr(self):
        """Test __repr__ returns a meaningful string."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        joint_pose = HandJointPose(pose, True, 0.01)

        repr_str = repr(joint_pose)

        assert "HandJointPose" in repr_str
        assert "Pose" in repr_str


class TestHandJointsStruct:
    """Tests for HandJoints struct."""

    def test_poses_access(self):
        """Test accessing all 26 joints via poses() method."""
        hand_joints = HandJoints()

        for i in range(26):
            joint = hand_joints.poses(i)
            assert joint is not None

    def test_poses_out_of_range(self):
        """Test that accessing out of range index raises IndexError."""
        hand_joints = HandJoints()

        with pytest.raises(IndexError):
            _ = hand_joints.poses(26)


class TestHandJointsRepr:
    """Tests for HandJoints __repr__ method."""

    def test_repr(self):
        """Test __repr__ returns a meaningful string."""
        hand_joints = HandJoints()

        repr_str = repr(hand_joints)
        assert "HandJoints" in repr_str


class TestHandPoseTConstruction:
    """Tests for HandPoseT construction and basic properties."""

    def test_default_construction(self):
        """Test default construction creates HandPoseT with pre-populated joints."""
        hand_pose = HandPoseT()

        assert hand_pose is not None
        assert hand_pose.joints is not None

    def test_parameterized_construction(self):
        """Test construction with joints."""
        joints = HandJoints()
        hand_pose = HandPoseT(joints)

        assert hand_pose.joints is not None


class TestHandPoseTRepr:
    """Tests for HandPoseT __repr__ method."""

    def test_repr_default(self):
        """Test __repr__ with default construction."""
        hand_pose = HandPoseT()

        repr_str = repr(hand_pose)
        assert "HandPoseT" in repr_str

    def test_repr_with_values(self):
        """Test __repr__ with joints set."""
        hand_pose = HandPoseT(HandJoints())

        repr_str = repr(hand_pose)
        assert "HandPoseT" in repr_str


class TestHandPoseRecordTimestamp:
    """Tests for HandPoseRecord with DeviceDataTimestamp."""

    def test_construction_with_timestamp(self):
        """Test HandPoseRecord carries DeviceDataTimestamp."""
        data = HandPoseT(HandJoints())
        ts = DeviceDataTimestamp(1000000000, 2000000000, 3000000000)
        record = HandPoseRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 1000000000
        assert record.timestamp.sample_time_local_common_clock == 2000000000
        assert record.timestamp.sample_time_raw_device_clock == 3000000000
        assert record.data is not None

    def test_default_construction(self):
        """Test default HandPoseRecord has no data."""
        record = HandPoseRecord()
        assert record.data is None
        assert record.timestamp is None

    def test_timestamp_fields(self):
        """Test all three DeviceDataTimestamp fields are accessible."""
        data = HandPoseT()
        ts = DeviceDataTimestamp(111, 222, 333)
        record = HandPoseRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 111
        assert record.timestamp.sample_time_local_common_clock == 222
        assert record.timestamp.sample_time_raw_device_clock == 333
