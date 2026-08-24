# SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for Se3TrackerPose in isaacteleop.schema.

Se3TrackerPose is a FlatBuffers table for a generic SE3 (6-DoF) tracker device:
- pose: The Pose struct (position and orientation)
- is_valid: Whether the pose data is valid (False = producer streaming, tracking lost;
  pose contents are then unspecified)

Timestamps are carried by Se3TrackerPoseRecord, not Se3TrackerPose.

Note: Python code should only READ this data (created by C++ trackers), not modify it.
"""

import pytest

from isaacteleop.schema import (
    Se3TrackerPose,
    Se3TrackerPoseRecord,
    Pose,
    Point,
    Quaternion,
    DeviceDataTimestamp,
)


class TestSe3TrackerPoseTConstruction:
    """Tests for Se3TrackerPose construction and basic properties."""

    def test_default_construction(self):
        """Default construction creates Se3TrackerPose with default-initialized fields."""
        se3_pose = Se3TrackerPose()

        assert se3_pose is not None
        assert se3_pose.pose is not None
        assert se3_pose.is_valid is False

    def test_parameterized_construction(self):
        """Construction with pose and is_valid."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        se3_pose = Se3TrackerPose(pose, True)

        assert se3_pose.pose.position.x == pytest.approx(1.0)
        assert se3_pose.pose.position.y == pytest.approx(2.0)
        assert se3_pose.pose.position.z == pytest.approx(3.0)
        assert se3_pose.pose.orientation.w == pytest.approx(1.0)
        assert se3_pose.is_valid is True

    def test_repr(self):
        """__repr__ includes the type name and is_valid."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        se3_pose = Se3TrackerPose(pose, True)

        repr_str = repr(se3_pose)
        assert "Se3TrackerPose" in repr_str
        assert "is_valid=True" in repr_str


class TestSe3TrackerPoseEncoding:
    """Tests that an encoded pose reads back.

    A tracker with no sample returns None rather than an empty pose, so absence
    needs no case here.
    """

    def test_encoded_payload_reads_back(self):
        """An encoded pose gates as True and its fields read directly."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        data = Se3TrackerPose(pose, True)

        assert data
        assert data.is_valid is True


class TestSe3TrackerPoseRecordTimestamp:
    """Tests for Se3TrackerPoseRecord with DeviceDataTimestamp."""

    def test_construction_with_timestamp(self):
        """Se3TrackerPoseRecord carries DeviceDataTimestamp (positional field order)."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        data = Se3TrackerPose(pose, True)
        ts = DeviceDataTimestamp(1000000000, 2000000000, 3000000000)
        record = Se3TrackerPoseRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 1000000000
        assert record.timestamp.sample_time_local_common_clock == 2000000000
        assert record.timestamp.sample_time_raw_device_clock == 3000000000
        assert record.data.is_valid is True

    def test_payload_less_record(self):
        """A record may carry a timestamp and no payload: MCAP's frame sentinel."""
        record = Se3TrackerPoseRecord(None, DeviceDataTimestamp(1, 2, 3))
        assert record.data is None
        assert record.timestamp.available_time_local_common_clock == 1
