# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for HeadPoseT in isaacteleop.schema.

HeadPoseT is a FlatBuffers table that represents head pose data:
- pose: The Pose struct (position and orientation)
- is_valid: Whether the head pose data is valid

Timestamps are carried by HeadPoseRecord, not HeadPoseT.

Note: Python code should only READ this data (created by C++ trackers), not modify it.
"""

import pytest

from isaacteleop.schema import (
    HeadPoseT,
    HeadPoseRecord,
    Pose,
    Point,
    Quaternion,
    DeviceDataTimestamp,
)


class TestHeadPoseTConstruction:
    """Tests for HeadPoseT construction and basic properties."""

    def test_default_construction(self):
        """Test default construction creates HeadPoseT with default-initialized fields."""
        head_pose = HeadPoseT()

        assert head_pose is not None
        assert head_pose.pose is not None
        assert head_pose.is_valid is False

    def test_parameterized_construction(self):
        """Test construction with pose and is_valid."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        head_pose = HeadPoseT(pose, True)

        assert head_pose.pose.position.x == pytest.approx(1.0)
        assert head_pose.pose.position.y == pytest.approx(2.0)
        assert head_pose.pose.position.z == pytest.approx(3.0)
        assert head_pose.pose.orientation.w == pytest.approx(1.0)
        assert head_pose.is_valid is True


class TestHeadPoseTRepr:
    """Tests for HeadPoseT __repr__ method."""

    def test_repr_default(self):
        """Test __repr__ with default construction."""
        head_pose = HeadPoseT()

        repr_str = repr(head_pose)
        assert "HeadPoseT" in repr_str

    def test_repr_with_values(self):
        """Test __repr__ with parameterized construction."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        head_pose = HeadPoseT(pose, True)

        repr_str = repr(head_pose)
        assert "HeadPoseT" in repr_str
        assert "is_valid=True" in repr_str


class TestHeadPoseRecordTimestamp:
    """Tests for HeadPoseRecord with DeviceDataTimestamp."""

    def test_construction_with_timestamp(self):
        """Test HeadPoseRecord carries DeviceDataTimestamp."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        data = HeadPoseT(pose, True)
        ts = DeviceDataTimestamp(1000000000, 2000000000, 3000000000)
        record = HeadPoseRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 1000000000
        assert record.timestamp.sample_time_local_common_clock == 2000000000
        assert record.timestamp.sample_time_raw_device_clock == 3000000000
        assert record.data.is_valid is True

    def test_default_construction(self):
        """Test default HeadPoseRecord has no data."""
        record = HeadPoseRecord()
        assert record.data is None
        assert record.timestamp is None

    def test_timestamp_fields(self):
        """Test all three DeviceDataTimestamp fields are accessible."""
        data = HeadPoseT()
        ts = DeviceDataTimestamp(111, 222, 333)
        record = HeadPoseRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 111
        assert record.timestamp.sample_time_local_common_clock == 222
        assert record.timestamp.sample_time_raw_device_clock == 333
