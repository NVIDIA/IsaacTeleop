# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for HandPoseT and related types in isaacteleop.schema.

HandPoseT is a FlatBuffers table that represents hand pose data:
- joints: HandJoints struct with a fixed-size poses array (length HandJoint.NUM_JOINTS; OpenXR order)

HandJoints is a struct with a fixed-size array of HandJointPose (length HandJoint.NUM_JOINTS).

HandJointPose is a struct containing:
- pose: The Pose (position and orientation)
- is_valid: Whether this joint data is valid
- radius: The radius of the joint (from OpenXR)

Timestamps are carried by HandPoseRecord, not HandPoseT.
"""

import gc

import numpy as np
import pytest

from isaacteleop.schema import (
    DeviceDataTimestamp,
    HandJoint,
    HandJointPose,
    HandJoints,
    HandPoseRecord,
    HandPoseT,
    Point,
    Pose,
    Quaternion,
)


def test_hand_joint_enum_sentinels():
    """HandJoint ordinals match expected OpenXR-style layout."""
    assert HandJoint.PALM == 0
    assert HandJoint.WRIST == 1
    assert HandJoint.THUMB_TIP == 5
    assert HandJoint.LITTLE_TIP == 25
    assert HandJoint.NUM_JOINTS == 26


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
        """Test accessing every joint slot via poses() method."""
        hand_joints = HandJoints()

        for i in range(HandJoint.NUM_JOINTS):
            joint = hand_joints.poses(i)
            assert joint is not None

    def test_poses_out_of_range(self):
        """Test that accessing out of range index raises IndexError."""
        hand_joints = HandJoints()

        with pytest.raises(IndexError):
            _ = hand_joints.poses(HandJoint.NUM_JOINTS)


class TestHandJointsFieldViews:
    """Tests for the bulk per-field HandJoints array accessors."""

    def test_shapes_and_dtypes(self):
        """The field views carry the layout HandInput declares."""
        joints = HandJoints()
        positions, orientations = joints.positions, joints.orientations
        radii, is_valid = joints.radii, joints.is_valid

        assert positions.shape == (HandJoint.NUM_JOINTS, 3)
        assert orientations.shape == (HandJoint.NUM_JOINTS, 4)
        assert radii.shape == (HandJoint.NUM_JOINTS,)
        assert is_valid.shape == (HandJoint.NUM_JOINTS,)
        assert positions.dtype == np.float32
        assert orientations.dtype == np.float32
        assert radii.dtype == np.float32
        assert is_valid.dtype == np.uint8

    def test_matches_per_joint_accessor(self):
        """Every row agrees with the corresponding poses(i) read.

        Each field gets its own value range so a view pointed at the wrong
        offset, or rows read at the wrong stride, cannot still compare equal.
        """
        num_joints = int(HandJoint.NUM_JOINTS)
        hand_joints = HandJoints()
        positions, orientations = hand_joints.positions, hand_joints.orientations
        radii, is_valid = hand_joints.radii, hand_joints.is_valid

        positions[:] = np.arange(num_joints * 3, dtype=np.float32).reshape(-1, 3)
        orientations[:] = np.arange(
            1000, 1000 + num_joints * 4, dtype=np.float32
        ).reshape(-1, 4)
        radii[:] = np.arange(5000, 5000 + num_joints, dtype=np.float32)
        is_valid[:] = np.arange(num_joints, dtype=np.uint8) % 2

        for i in range(num_joints):
            joint = hand_joints.poses(i)
            assert positions[i].tolist() == [
                joint.pose.position.x,
                joint.pose.position.y,
                joint.pose.position.z,
            ]
            assert positions[i].tolist() == [3 * i, 3 * i + 1, 3 * i + 2]
            assert orientations[i].tolist() == [
                joint.pose.orientation.x,
                joint.pose.orientation.y,
                joint.pose.orientation.z,
                joint.pose.orientation.w,
            ]
            assert orientations[i].tolist() == [
                1000 + 4 * i,
                1000 + 4 * i + 1,
                1000 + 4 * i + 2,
                1000 + 4 * i + 3,
            ]
            assert radii[i] == joint.radius == 5000 + i
            assert is_valid[i] == (1 if joint.is_valid else 0) == i % 2

    def test_returns_strided_views(self):
        """Arrays alias the interleaved joint storage instead of copying it."""
        hand_joints = HandJoints()
        positions, orientations = hand_joints.positions, hand_joints.orientations
        radii, is_valid = hand_joints.radii, hand_joints.is_valid

        stride = positions.strides[0]
        for array in (positions, orientations, radii, is_valid):
            assert not array.flags.owndata
            # Row stride is one whole HandJointPose, not the packed field width.
            assert array.strides[0] == stride
            assert not array.flags.c_contiguous

    def test_views_write_through_to_schema(self):
        """Views are writable and alias schema state; callers must copy to detach."""
        hand_joints = HandJoints()
        positions = hand_joints.positions

        positions[0, 0] = 42.0

        assert hand_joints.poses(0).pose.position.x == 42.0

    def test_views_keep_owner_alive(self):
        """A view outlives the last direct reference to the table it came from."""
        pose = HandPoseT()
        positions = pose.joints.positions
        expected = np.arange(int(HandJoint.NUM_JOINTS) * 3, dtype=np.float32).reshape(
            -1, 3
        )
        positions[:] = expected

        del pose
        gc.collect()

        # Would read freed memory if the base object chain were not held.
        assert positions.shape == (HandJoint.NUM_JOINTS, 3)
        assert np.array_equal(np.asarray(positions), expected)

    def test_copy_yields_packed_writable_array(self):
        """The documented escape hatch produces contiguous, writable data."""
        packed = HandJoints().positions.copy()

        assert packed.flags.c_contiguous
        assert packed.flags.writeable


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
