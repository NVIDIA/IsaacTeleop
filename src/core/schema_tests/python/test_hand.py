# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for HandPoseT and related types in teleopcore.schema.

HandPoseT is a FlatBuffers table (read-only from Python) that represents hand pose data:
- joints: HandJoints struct containing 26 HandJointPose entries (XR_HAND_JOINT_COUNT_EXT)
- is_active: Whether the hand pose data is active
- timestamp: Timestamp struct with device and common time

HandJoints is a struct with a fixed-size array of 26 HandJointPose entries.

HandJointPose is a struct containing:
- pose: The Pose (position and orientation)
- is_valid: Whether this joint data is valid
- radius: The radius of the joint (from OpenXR)

Note: Python code should only READ this data (created by C++ trackers), not modify it.
"""

import pytest

from teleopcore.schema import (
    HandPoseT,
    HandJoints,
    HandJointPose,
    Pose,
    Point,
    Quaternion,
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

    def test_length(self):
        """Test that HandJoints has exactly 26 joints."""
        hand_joints = HandJoints()

        assert len(hand_joints) == 26

    def test_getitem_access(self):
        """Test accessing joints via __getitem__ (indexing)."""
        hand_joints = HandJoints()

        # Should be able to access all 26 joints.
        for i in range(26):
            joint = hand_joints[i]
            assert joint is not None

    def test_poses_method(self):
        """Test accessing joints via poses() method."""
        hand_joints = HandJoints()

        # Should be able to access via poses method.
        joint = hand_joints.poses(0)
        assert joint is not None

    def test_index_out_of_range(self):
        """Test that accessing out of range index raises IndexError."""
        hand_joints = HandJoints()

        with pytest.raises(IndexError):
            _ = hand_joints[26]  # Should fail (0-25 are valid)


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
        """Test default construction creates HandPoseT with None joints."""
        hand_pose = HandPoseT()

        assert hand_pose is not None
        assert hand_pose.joints is None
        assert hand_pose.is_active is False
        assert hand_pose.timestamp is None


class TestHandPoseTRepr:
    """Tests for HandPoseT __repr__ method."""

    def test_repr_with_no_joints(self):
        """Test __repr__ when joints is None."""
        hand_pose = HandPoseT()

        repr_str = repr(hand_pose)
        assert "HandPoseT" in repr_str
        assert "None" in repr_str

