# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for HandPoseT and related types in teleopcore.schema.

HandPoseT is a FlatBuffers table (mutable object-API) that represents hand pose data:
- joints: HandJoints struct containing 26 HandJointPose entries (XR_HAND_JOINT_COUNT_EXT)
- is_valid: Whether the hand pose data is valid
- timestamp: The timestamp in XrTime format (int64)

HandJoints is a struct with a fixed-size array of 26 HandJointPose entries.

HandJointPose is a struct containing:
- pose: The Pose (position and orientation)
- is_valid: Whether this joint data is valid
- radius: The radius of the joint (from OpenXR)
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
        """Test that HandJoints has exactly 26 entries."""
        joints = HandJoints()

        assert len(joints) == 26

    def test_getitem_access(self):
        """Test accessing joints via __getitem__."""
        joints = HandJoints()

        # Access first and last joints.
        first_joint = joints[0]
        last_joint = joints[25]

        assert first_joint is not None
        assert last_joint is not None

    def test_poses_method(self):
        """Test accessing joints via poses() method."""
        joints = HandJoints()

        first_joint = joints.poses(0)
        last_joint = joints.poses(25)

        assert first_joint is not None
        assert last_joint is not None

    def test_index_out_of_range(self):
        """Test that accessing out-of-range indices raises IndexError."""
        joints = HandJoints()

        with pytest.raises(IndexError):
            _ = joints[26]

        with pytest.raises(IndexError):
            _ = joints.poses(26)


class TestHandJointsRepr:
    """Tests for HandJoints __repr__ method."""

    def test_repr(self):
        """Test __repr__ returns a meaningful string."""
        joints = HandJoints()
        repr_str = repr(joints)

        assert "HandJoints" in repr_str
        assert "26" in repr_str


class TestHandPoseTConstruction:
    """Tests for HandPoseT construction."""

    def test_default_construction(self):
        """Test default construction creates HandPoseT with default values."""
        hand_pose = HandPoseT()

        assert hand_pose is not None
        assert hand_pose.joints is None
        assert hand_pose.is_active is False
        assert hand_pose.timestamp == 0

    def test_is_active_can_be_set(self):
        """Test that is_active can be set to True."""
        hand_pose = HandPoseT()
        hand_pose.is_active = True

        assert hand_pose.is_active is True

    def test_timestamp_can_be_set(self):
        """Test that timestamp can be set."""
        hand_pose = HandPoseT()
        hand_pose.timestamp = 1234567890123456789

        assert hand_pose.timestamp == 1234567890123456789


class TestHandPoseTJoints:
    """Tests for HandPoseT joints property."""

    def test_set_joints_convenience_method(self):
        """Test setting joints using the convenience method."""
        hand_pose = HandPoseT()

        # Create 26 joint poses.
        joint_poses = []
        for i in range(26):
            position = Point(float(i), float(i * 2), float(i * 3))
            orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
            pose = Pose(position, orientation)
            joint_pose = HandJointPose(pose, True, 0.01 + i * 0.001)
            joint_poses.append(joint_pose)

        hand_pose.set_joints(joint_poses)

        assert hand_pose.joints is not None
        assert len(hand_pose.joints) == 26

    def test_set_joints_wrong_count_raises_error(self):
        """Test that setting wrong number of joints raises an error."""
        hand_pose = HandPoseT()

        # Create only 10 joint poses (should fail).
        joint_poses = []
        for i in range(10):
            pose = Pose(Point(), Quaternion())
            joint_pose = HandJointPose(pose, False, 0.0)
            joint_poses.append(joint_pose)

        with pytest.raises(RuntimeError):
            hand_pose.set_joints(joint_poses)


class TestHandPoseTFullUsage:
    """Tests for HandPoseT with all fields set."""

    def test_full_hand_pose_data(self):
        """Test creating a complete HandPoseT with all fields."""
        hand_pose = HandPoseT()

        # Create and set joints.
        joint_poses = []
        for i in range(26):
            position = Point(float(i), 0.0, 0.0)
            orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
            pose = Pose(position, orientation)
            joint_pose = HandJointPose(pose, True, 0.01)
            joint_poses.append(joint_pose)

        hand_pose.set_joints(joint_poses)
        hand_pose.is_active = True
        hand_pose.timestamp = 9876543210

        # Verify all fields.
        assert hand_pose.joints is not None
        assert len(hand_pose.joints) == 26
        assert hand_pose.is_active is True
        assert hand_pose.timestamp == 9876543210

        # Verify a specific joint.
        joint_5 = hand_pose.joints[5]
        assert joint_5.pose.position.x == pytest.approx(5.0)

    def test_access_all_joints(self):
        """Test accessing all 26 joints after setting them."""
        hand_pose = HandPoseT()

        joint_poses = []
        for i in range(26):
            position = Point(float(i), float(i * 2), float(i * 3))
            orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
            pose = Pose(position, orientation)
            joint_pose = HandJointPose(pose, True, 0.01 + i * 0.001)
            joint_poses.append(joint_pose)

        hand_pose.set_joints(joint_poses)

        # Verify each joint.
        for i in range(26):
            joint = hand_pose.joints[i]
            assert joint.pose.position.x == pytest.approx(float(i))
            assert joint.pose.position.y == pytest.approx(float(i * 2))
            assert joint.pose.position.z == pytest.approx(float(i * 3))
            assert joint.is_valid is True
            assert joint.radius == pytest.approx(0.01 + i * 0.001)


class TestHandPoseTRepr:
    """Tests for HandPoseT __repr__ method."""

    def test_repr_with_no_joints(self):
        """Test __repr__ when joints are not set."""
        hand_pose = HandPoseT()
        repr_str = repr(hand_pose)

        assert "HandPoseT" in repr_str
        assert "None" in repr_str
        assert "is_active=False" in repr_str

    def test_repr_with_joints(self):
        """Test __repr__ when joints are set."""
        hand_pose = HandPoseT()

        joint_poses = []
        for _ in range(26):
            pose = Pose(Point(), Quaternion())
            joint_poses.append(HandJointPose(pose, False, 0.0))

        hand_pose.set_joints(joint_poses)
        hand_pose.is_active = True

        repr_str = repr(hand_pose)

        assert "HandPoseT" in repr_str
        assert "HandJoints" in repr_str
        assert "is_active=True" in repr_str


class TestHandPoseTDataTypes:
    """Tests for HandPoseT with various input types."""

    def test_large_timestamp(self):
        """Test HandPoseT with a large timestamp value (int64 range)."""
        hand_pose = HandPoseT()
        large_timestamp = 9223372036854775807  # Max int64

        hand_pose.timestamp = large_timestamp

        assert hand_pose.timestamp == large_timestamp

    def test_negative_timestamp(self):
        """Test HandPoseT with a negative timestamp value."""
        hand_pose = HandPoseT()
        negative_timestamp = -1234567890

        hand_pose.timestamp = negative_timestamp

        assert hand_pose.timestamp == negative_timestamp

