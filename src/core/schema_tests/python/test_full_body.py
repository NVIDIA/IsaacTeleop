# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for FullBodyPoseT and related types in isaacteleop.schema.

FullBodyPoseT is a FlatBuffers table that represents full body pose data:
- joints: BodyJoints struct containing 24 BodyJointPose entries (XR_BD_body_tracking)

BodyJoints is a struct with a fixed-size array of 24 BodyJointPose entries.

BodyJointPose is a struct containing:
- pose: The Pose (position and orientation)
- is_valid: Whether this joint data is valid

Timestamps are carried by FullBodyPoseRecord, not FullBodyPoseT.

Joint indices follow XrBodyJointBD enum:
  0: Pelvis, 1-2: Left/Right Hip, 3: Spine1, 4-5: Left/Right Knee,
  6: Spine2, 7-8: Left/Right Ankle, 9: Spine3, 10-11: Left/Right Foot,
  12: Neck, 13-14: Left/Right Collar, 15: Head, 16-17: Left/Right Shoulder,
  18-19: Left/Right Elbow, 20-21: Left/Right Wrist, 22-23: Left/Right Hand
"""

import pytest

from isaacteleop.schema import (
    FullBodyPoseT,
    FullBodyPoseRecord,
    BodyJoints,
    BodyJointPose,
    BodyJoint,
    Pose,
    Point,
    Quaternion,
    DeviceDataTimestamp,
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


class TestBodyJointsStruct:
    """Tests for BodyJoints struct."""

    def test_joints_access(self):
        """Test accessing all 24 joints via joints() method."""
        body_joints = BodyJoints()

        for i in range(24):
            joint = body_joints.joints(i)
            assert joint is not None

    def test_joints_out_of_range(self):
        """Test that accessing out of range index raises IndexError."""
        body_joints = BodyJoints()

        with pytest.raises(IndexError):
            _ = body_joints.joints(24)


class TestBodyJointsRepr:
    """Tests for BodyJoints __repr__ method."""

    def test_repr(self):
        """Test __repr__ returns a meaningful string."""
        body_joints = BodyJoints()

        repr_str = repr(body_joints)
        assert "BodyJoints" in repr_str


class TestFullBodyPoseTConstruction:
    """Tests for FullBodyPoseT construction and basic properties."""

    def test_default_construction(self):
        """Test default construction creates FullBodyPoseT with pre-populated joints."""
        body_pose = FullBodyPoseT()

        assert body_pose is not None
        assert body_pose.joints is not None

    def test_parameterized_construction(self):
        """Test construction with joints."""
        joints = BodyJoints()
        body_pose = FullBodyPoseT(joints)

        assert body_pose.joints is not None


class TestFullBodyPoseTRepr:
    """Tests for FullBodyPoseT __repr__ method."""

    def test_repr_default(self):
        """Test __repr__ with default construction."""
        body_pose = FullBodyPoseT()

        repr_str = repr(body_pose)
        assert "FullBodyPoseT" in repr_str


class TestBodyJointEnum:
    """Tests for BodyJoint enum (joint index mapping for XR_BD_body_tracking)."""

    def test_all_joint_values_exist(self):
        """Test that all expected BodyJoint enum values exist."""
        assert BodyJoint.PELVIS is not None
        assert BodyJoint.LEFT_HIP is not None
        assert BodyJoint.RIGHT_HIP is not None
        assert BodyJoint.SPINE1 is not None
        assert BodyJoint.LEFT_KNEE is not None
        assert BodyJoint.RIGHT_KNEE is not None
        assert BodyJoint.SPINE2 is not None
        assert BodyJoint.LEFT_ANKLE is not None
        assert BodyJoint.RIGHT_ANKLE is not None
        assert BodyJoint.SPINE3 is not None
        assert BodyJoint.LEFT_FOOT is not None
        assert BodyJoint.RIGHT_FOOT is not None
        assert BodyJoint.NECK is not None
        assert BodyJoint.LEFT_COLLAR is not None
        assert BodyJoint.RIGHT_COLLAR is not None
        assert BodyJoint.HEAD is not None
        assert BodyJoint.LEFT_SHOULDER is not None
        assert BodyJoint.RIGHT_SHOULDER is not None
        assert BodyJoint.LEFT_ELBOW is not None
        assert BodyJoint.RIGHT_ELBOW is not None
        assert BodyJoint.LEFT_WRIST is not None
        assert BodyJoint.RIGHT_WRIST is not None
        assert BodyJoint.LEFT_HAND is not None
        assert BodyJoint.RIGHT_HAND is not None

    def test_joint_values(self):
        """Test that BodyJoint values match expected indices."""
        assert int(BodyJoint.PELVIS) == 0
        assert int(BodyJoint.LEFT_HIP) == 1
        assert int(BodyJoint.RIGHT_HIP) == 2
        assert int(BodyJoint.SPINE1) == 3
        assert int(BodyJoint.LEFT_KNEE) == 4
        assert int(BodyJoint.RIGHT_KNEE) == 5
        assert int(BodyJoint.SPINE2) == 6
        assert int(BodyJoint.LEFT_ANKLE) == 7
        assert int(BodyJoint.RIGHT_ANKLE) == 8
        assert int(BodyJoint.SPINE3) == 9
        assert int(BodyJoint.LEFT_FOOT) == 10
        assert int(BodyJoint.RIGHT_FOOT) == 11
        assert int(BodyJoint.NECK) == 12
        assert int(BodyJoint.LEFT_COLLAR) == 13
        assert int(BodyJoint.RIGHT_COLLAR) == 14
        assert int(BodyJoint.HEAD) == 15
        assert int(BodyJoint.LEFT_SHOULDER) == 16
        assert int(BodyJoint.RIGHT_SHOULDER) == 17
        assert int(BodyJoint.LEFT_ELBOW) == 18
        assert int(BodyJoint.RIGHT_ELBOW) == 19
        assert int(BodyJoint.LEFT_WRIST) == 20
        assert int(BodyJoint.RIGHT_WRIST) == 21
        assert int(BodyJoint.LEFT_HAND) == 22
        assert int(BodyJoint.RIGHT_HAND) == 23

    def test_all_joint_indices_accessible(self):
        """Test that all BodyJoint values can be used to index BodyJoints."""
        body_joints = BodyJoints()

        all_joints = [
            BodyJoint.PELVIS,
            BodyJoint.LEFT_HIP,
            BodyJoint.RIGHT_HIP,
            BodyJoint.SPINE1,
            BodyJoint.LEFT_KNEE,
            BodyJoint.RIGHT_KNEE,
            BodyJoint.SPINE2,
            BodyJoint.LEFT_ANKLE,
            BodyJoint.RIGHT_ANKLE,
            BodyJoint.SPINE3,
            BodyJoint.LEFT_FOOT,
            BodyJoint.RIGHT_FOOT,
            BodyJoint.NECK,
            BodyJoint.LEFT_COLLAR,
            BodyJoint.RIGHT_COLLAR,
            BodyJoint.HEAD,
            BodyJoint.LEFT_SHOULDER,
            BodyJoint.RIGHT_SHOULDER,
            BodyJoint.LEFT_ELBOW,
            BodyJoint.RIGHT_ELBOW,
            BodyJoint.LEFT_WRIST,
            BodyJoint.RIGHT_WRIST,
            BodyJoint.LEFT_HAND,
            BodyJoint.RIGHT_HAND,
        ]
        assert len(all_joints) == 24

        for joint in all_joints:
            joint_pose = body_joints.joints(int(joint))
            assert joint_pose is not None

    def test_enum_int_conversion(self):
        """Test that BodyJoint values can be converted to integers."""
        assert int(BodyJoint.PELVIS) == 0
        assert int(BodyJoint.HEAD) == 15
        assert int(BodyJoint.RIGHT_HAND) == 23


class TestFullBodyPoseRecordTimestamp:
    """Tests for FullBodyPoseRecord with DeviceDataTimestamp."""

    def test_construction_with_timestamp(self):
        """Test FullBodyPoseRecord carries DeviceDataTimestamp."""
        data = FullBodyPoseT()
        ts = DeviceDataTimestamp(1000000000, 2000000000, 3000000000)
        record = FullBodyPoseRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 1000000000
        assert record.timestamp.sample_time_local_common_clock == 2000000000
        assert record.timestamp.sample_time_raw_device_clock == 3000000000
        assert record.data is not None

    def test_default_construction(self):
        """Test default FullBodyPoseRecord has no data."""
        record = FullBodyPoseRecord()
        assert record.data is None

    def test_timestamp_fields(self):
        """Test all three DeviceDataTimestamp fields are accessible."""
        data = FullBodyPoseT()
        ts = DeviceDataTimestamp(111, 222, 333)
        record = FullBodyPoseRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 111
        assert record.timestamp.sample_time_local_common_clock == 222
        assert record.timestamp.sample_time_raw_device_clock == 333


class TestDeprecatedPicoAliases:
    """Deprecated ``...Pico`` names still resolve to the renamed generic types and
    now emit a DeprecationWarning on access."""

    def test_aliases_resolve_and_warn(self):
        """Each legacy schema name warns and resolves to its renamed generic type."""
        from isaacteleop import schema

        cases = [
            ("FullBodyPosePicoT", "FullBodyPoseT"),
            ("FullBodyPosePicoTrackedT", "FullBodyPoseTrackedT"),
            ("FullBodyPosePicoRecord", "FullBodyPoseRecord"),
            ("BodyJointsPico", "BodyJoints"),
            ("BodyJointPico", "BodyJoint"),
        ]
        for old, new in cases:
            with pytest.warns(DeprecationWarning, match=old):
                deprecated = getattr(schema, old)
            assert deprecated is getattr(schema, new)

        # The aliased enum still exposes the same joint members/values.
        with pytest.warns(DeprecationWarning, match="BodyJointPico"):
            assert int(schema.BodyJointPico.RIGHT_HAND) == 23
