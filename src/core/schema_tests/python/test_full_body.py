# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for FullBodyPosePicoT and related types in isaacteleop.schema.

FullBodyPosePicoT is a FlatBuffers table that represents full body pose data:
- joints: BodyJointsPico struct containing 24 BodyJointPose entries (XR_BD_body_tracking)
- timestamp: Timestamp struct with device and common time

BodyJointsPico is a struct with a fixed-size array of 24 BodyJointPose entries.

BodyJointPose is a struct containing:
- pose: The Pose (position and orientation)
- is_valid: Whether this joint data is valid

Joint indices follow XrBodyJointBD enum:
  0: Pelvis, 1-2: Left/Right Hip, 3: Spine1, 4-5: Left/Right Knee,
  6: Spine2, 7-8: Left/Right Ankle, 9: Spine3, 10-11: Left/Right Foot,
  12: Neck, 13-14: Left/Right Collar, 15: Head, 16-17: Left/Right Shoulder,
  18-19: Left/Right Elbow, 20-21: Left/Right Wrist, 22-23: Left/Right Hand
"""

import pytest

from isaacteleop.schema import (
    FullBodyPosePicoT,
    BodyJointsPico,
    BodyJointPose,
    BodyJointPico,
    Pose,
    Point,
    Quaternion,
    Timestamp,
)


class TestBodyJointPoseConstruction:
    """Tests for BodyJointPose construction."""

    def test_default_construction(self):
        """Test default construction creates BodyJointPose with default values."""
        joint_pose = BodyJointPose()

        assert joint_pose is not None
        # Default pose values should be zero.
        assert joint_pose.pose.position.x == 0.0
        assert joint_pose.pose.position.y == 0.0
        assert joint_pose.pose.position.z == 0.0
        assert joint_pose.is_valid is False

    def test_construction_with_values(self):
        """Test construction with position, orientation, and is_valid."""
        position = Point(1.0, 2.0, 3.0)
        orientation = Quaternion(0.0, 0.0, 0.0, 1.0)
        pose = Pose(position, orientation)
        joint_pose = BodyJointPose(pose, True)

        assert joint_pose.pose.position.x == pytest.approx(1.0)
        assert joint_pose.pose.position.y == pytest.approx(2.0)
        assert joint_pose.pose.position.z == pytest.approx(3.0)
        assert joint_pose.is_valid is True


class TestBodyJointPoseAccess:
    """Tests for BodyJointPose property access."""

    def test_pose_access(self):
        """Test accessing pose property."""
        position = Point(1.5, 2.5, 3.5)
        orientation = Quaternion(0.1, 0.2, 0.3, 0.9)
        pose = Pose(position, orientation)
        joint_pose = BodyJointPose(pose, True)

        assert joint_pose.pose.position.x == pytest.approx(1.5)
        assert joint_pose.pose.orientation.w == pytest.approx(0.9)

    def test_is_valid_access(self):
        """Test accessing is_valid property."""
        pose = Pose(Point(), Quaternion())
        joint_pose = BodyJointPose(pose, True)

        assert joint_pose.is_valid is True


class TestBodyJointPoseRepr:
    """Tests for BodyJointPose __repr__ method."""

    def test_repr(self):
        """Test __repr__ returns a meaningful string."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        joint_pose = BodyJointPose(pose, True)

        repr_str = repr(joint_pose)

        assert "BodyJointPose" in repr_str
        assert "Pose" in repr_str


class TestBodyJointsPicoStruct:
    """Tests for BodyJointsPico struct."""

    def test_joints_access(self):
        """Test accessing all 24 joints via joints() method."""
        body_joints = BodyJointsPico()

        for i in range(24):
            joint = body_joints.joints(i)
            assert joint is not None

    def test_joints_out_of_range(self):
        """Test that accessing out of range index raises IndexError."""
        body_joints = BodyJointsPico()

        with pytest.raises(IndexError):
            _ = body_joints.joints(24)


class TestBodyJointsPicoRepr:
    """Tests for BodyJointsPico __repr__ method."""

    def test_repr(self):
        """Test __repr__ returns a meaningful string."""
        body_joints = BodyJointsPico()

        repr_str = repr(body_joints)
        assert "BodyJointsPico" in repr_str


class TestFullBodyPosePicoTConstruction:
    """Tests for FullBodyPosePicoT construction and basic properties."""

    def test_default_construction(self):
        """Test default construction creates FullBodyPosePicoT with default-initialized fields."""
        body_pose = FullBodyPosePicoT()

        assert body_pose is not None
        assert body_pose.joints is not None
        assert body_pose.timestamp is not None

    def test_parameterized_construction(self):
        """Test construction with joints and timestamp."""
        joints = BodyJointsPico()
        timestamp = Timestamp(device_time=12345, common_time=67890)
        body_pose = FullBodyPosePicoT(joints, timestamp)

        assert body_pose.joints is not None
        assert body_pose.timestamp.device_time == 12345
        assert body_pose.timestamp.common_time == 67890


class TestFullBodyPosePicoTRepr:
    """Tests for FullBodyPosePicoT __repr__ method."""

    def test_repr_default(self):
        """Test __repr__ with default construction."""
        body_pose = FullBodyPosePicoT()

        repr_str = repr(body_pose)
        assert "FullBodyPosePicoT" in repr_str


class TestBodyJointPicoEnum:
    """Tests for BodyJointPico enum (joint index mapping for XR_BD_body_tracking)."""

    def test_all_joint_values_exist(self):
        """Test that all expected BodyJointPico enum values exist."""
        # All 24 joints should be accessible.
        assert BodyJointPico.PELVIS is not None
        assert BodyJointPico.LEFT_HIP is not None
        assert BodyJointPico.RIGHT_HIP is not None
        assert BodyJointPico.SPINE1 is not None
        assert BodyJointPico.LEFT_KNEE is not None
        assert BodyJointPico.RIGHT_KNEE is not None
        assert BodyJointPico.SPINE2 is not None
        assert BodyJointPico.LEFT_ANKLE is not None
        assert BodyJointPico.RIGHT_ANKLE is not None
        assert BodyJointPico.SPINE3 is not None
        assert BodyJointPico.LEFT_FOOT is not None
        assert BodyJointPico.RIGHT_FOOT is not None
        assert BodyJointPico.NECK is not None
        assert BodyJointPico.LEFT_COLLAR is not None
        assert BodyJointPico.RIGHT_COLLAR is not None
        assert BodyJointPico.HEAD is not None
        assert BodyJointPico.LEFT_SHOULDER is not None
        assert BodyJointPico.RIGHT_SHOULDER is not None
        assert BodyJointPico.LEFT_ELBOW is not None
        assert BodyJointPico.RIGHT_ELBOW is not None
        assert BodyJointPico.LEFT_WRIST is not None
        assert BodyJointPico.RIGHT_WRIST is not None
        assert BodyJointPico.LEFT_HAND is not None
        assert BodyJointPico.RIGHT_HAND is not None

    def test_joint_values(self):
        """Test that BodyJointPico values match expected indices."""
        assert int(BodyJointPico.PELVIS) == 0
        assert int(BodyJointPico.LEFT_HIP) == 1
        assert int(BodyJointPico.RIGHT_HIP) == 2
        assert int(BodyJointPico.SPINE1) == 3
        assert int(BodyJointPico.LEFT_KNEE) == 4
        assert int(BodyJointPico.RIGHT_KNEE) == 5
        assert int(BodyJointPico.SPINE2) == 6
        assert int(BodyJointPico.LEFT_ANKLE) == 7
        assert int(BodyJointPico.RIGHT_ANKLE) == 8
        assert int(BodyJointPico.SPINE3) == 9
        assert int(BodyJointPico.LEFT_FOOT) == 10
        assert int(BodyJointPico.RIGHT_FOOT) == 11
        assert int(BodyJointPico.NECK) == 12
        assert int(BodyJointPico.LEFT_COLLAR) == 13
        assert int(BodyJointPico.RIGHT_COLLAR) == 14
        assert int(BodyJointPico.HEAD) == 15
        assert int(BodyJointPico.LEFT_SHOULDER) == 16
        assert int(BodyJointPico.RIGHT_SHOULDER) == 17
        assert int(BodyJointPico.LEFT_ELBOW) == 18
        assert int(BodyJointPico.RIGHT_ELBOW) == 19
        assert int(BodyJointPico.LEFT_WRIST) == 20
        assert int(BodyJointPico.RIGHT_WRIST) == 21
        assert int(BodyJointPico.LEFT_HAND) == 22
        assert int(BodyJointPico.RIGHT_HAND) == 23

    def test_all_joint_indices_accessible(self):
        """Test that all BodyJointPico values can be used to index BodyJointsPico."""
        body_joints = BodyJointsPico()

        # Test each joint index explicitly.
        all_joints = [
            BodyJointPico.PELVIS,
            BodyJointPico.LEFT_HIP,
            BodyJointPico.RIGHT_HIP,
            BodyJointPico.SPINE1,
            BodyJointPico.LEFT_KNEE,
            BodyJointPico.RIGHT_KNEE,
            BodyJointPico.SPINE2,
            BodyJointPico.LEFT_ANKLE,
            BodyJointPico.RIGHT_ANKLE,
            BodyJointPico.SPINE3,
            BodyJointPico.LEFT_FOOT,
            BodyJointPico.RIGHT_FOOT,
            BodyJointPico.NECK,
            BodyJointPico.LEFT_COLLAR,
            BodyJointPico.RIGHT_COLLAR,
            BodyJointPico.HEAD,
            BodyJointPico.LEFT_SHOULDER,
            BodyJointPico.RIGHT_SHOULDER,
            BodyJointPico.LEFT_ELBOW,
            BodyJointPico.RIGHT_ELBOW,
            BodyJointPico.LEFT_WRIST,
            BodyJointPico.RIGHT_WRIST,
            BodyJointPico.LEFT_HAND,
            BodyJointPico.RIGHT_HAND,
        ]
        assert len(all_joints) == 24

        for joint in all_joints:
            joint_pose = body_joints.joints(int(joint))
            assert joint_pose is not None

    def test_enum_int_conversion(self):
        """Test that BodyJointPico values can be converted to integers."""
        assert int(BodyJointPico.PELVIS) == 0
        assert int(BodyJointPico.HEAD) == 15
        assert int(BodyJointPico.RIGHT_HAND) == 23
