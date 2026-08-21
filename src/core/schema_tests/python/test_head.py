# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for HeadPose in isaacteleop.schema.

HeadPose is a FlatBuffers table that represents head pose data:
- pose: The Pose struct (position and orientation)
- is_valid: Whether the pose value is valid to read (OpenXR VALID)
- is_tracked: Whether the pose is actively tracked (OpenXR TRACKED)

Timestamps are carried by HeadPoseRecord, not HeadPose.

Note: Python code should only READ this data (created by C++ trackers), not modify it.
"""

import pytest

from isaacteleop.schema import (
    HeadPose,
    HeadPoseRecord,
    Pose,
    Point,
    Quaternion,
    DeviceDataTimestamp,
)


class TestHeadPoseTConstruction:
    """Tests for HeadPose construction and basic properties."""

    def test_default_construction(self):
        """Test default construction creates HeadPose with default-initialized fields."""
        head_pose = HeadPose()

        assert head_pose is not None
        assert head_pose.pose is not None
        assert head_pose.is_valid is False
        assert head_pose.is_tracked is False

    def test_parameterized_construction(self):
        """Test construction with pose, is_valid, and is_tracked."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        head_pose = HeadPose(pose, True, True)

        assert head_pose.pose.position.x == pytest.approx(1.0)
        assert head_pose.pose.position.y == pytest.approx(2.0)
        assert head_pose.pose.position.z == pytest.approx(3.0)
        assert head_pose.pose.orientation.w == pytest.approx(1.0)
        assert head_pose.is_valid is True
        assert head_pose.is_tracked is True

    def test_parameterized_construction_defaults_is_tracked_false(self):
        """Two-arg constructor keeps is_tracked=False for back-compat."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        head_pose = HeadPose(pose, True)

        assert head_pose.is_valid is True
        assert head_pose.is_tracked is False


class TestHeadPoseTRepr:
    """Tests for HeadPose __repr__ method."""

    def test_repr_default(self):
        """Test __repr__ with default construction."""
        head_pose = HeadPose()

        repr_str = repr(head_pose)
        assert "HeadPose" in repr_str

    def test_repr_with_values(self):
        """Test __repr__ with parameterized construction."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        head_pose = HeadPose(pose, True, True)

        repr_str = repr(head_pose)
        assert "HeadPose" in repr_str
        assert "is_valid=True" in repr_str
        assert "is_tracked=True" in repr_str


class TestHeadPoseRecordTimestamp:
    """Tests for HeadPoseRecord with DeviceDataTimestamp."""

    def test_construction_with_timestamp(self):
        """Test HeadPoseRecord carries DeviceDataTimestamp."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        data = HeadPose(pose, True, True)
        ts = DeviceDataTimestamp(1000000000, 2000000000, 3000000000)
        record = HeadPoseRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 1000000000
        assert record.timestamp.sample_time_local_common_clock == 2000000000
        assert record.timestamp.sample_time_raw_device_clock == 3000000000
        assert record.data.is_valid is True
        assert record.data.is_tracked is True

    def test_payload_less_record(self):
        """A record may carry a timestamp and no payload: MCAP's frame sentinel."""
        record = HeadPoseRecord(None, DeviceDataTimestamp(1, 2, 3))
        assert record.data is None
        assert record.timestamp.available_time_local_common_clock == 1

    def test_timestamp_fields(self):
        """Test all three DeviceDataTimestamp fields are accessible."""
        data = HeadPose()
        ts = DeviceDataTimestamp(111, 222, 333)
        record = HeadPoseRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 111
        assert record.timestamp.sample_time_local_common_clock == 222
        assert record.timestamp.sample_time_raw_device_clock == 333
