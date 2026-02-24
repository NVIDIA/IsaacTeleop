# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for HeadPoseT in isaacteleop.schema.

HeadPoseT is a FlatBuffers table that represents head pose data:
- pose: The Pose struct (position and orientation)
- is_valid: Whether the head pose data is valid
- timestamp: Timestamp struct with device and common time
"""

import pytest

from isaacteleop.schema import HeadPoseT, Pose, Point, Quaternion, Timestamp


class TestHeadPoseTConstruction:
    """Tests for HeadPoseT construction and basic properties."""

    def test_default_construction(self):
        """Test default construction creates HeadPoseT with default-initialized fields."""
        head_pose = HeadPoseT()

        assert head_pose is not None
        assert head_pose.pose is not None
        assert head_pose.is_valid is False
        assert head_pose.timestamp is not None

    def test_parameterized_construction(self):
        """Test construction with pose, is_valid, and timestamp."""
        pose = Pose(Point(1.0, 2.0, 3.0), Quaternion(0.0, 0.0, 0.0, 1.0))
        timestamp = Timestamp(device_time=12345, common_time=67890)
        head_pose = HeadPoseT(pose, True, timestamp)

        assert head_pose.pose.position.x == pytest.approx(1.0)
        assert head_pose.pose.position.y == pytest.approx(2.0)
        assert head_pose.pose.position.z == pytest.approx(3.0)
        assert head_pose.pose.orientation.w == pytest.approx(1.0)
        assert head_pose.is_valid is True
        assert head_pose.timestamp.device_time == 12345
        assert head_pose.timestamp.common_time == 67890


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
        head_pose = HeadPoseT(pose, True, Timestamp(100, 200))

        repr_str = repr(head_pose)
        assert "HeadPoseT" in repr_str
        assert "is_valid=True" in repr_str
