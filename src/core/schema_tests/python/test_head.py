# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for HeadPoseT in isaacteleop.schema.

HeadPoseT is a FlatBuffers struct (read-only from Python) that represents head pose data:
- pose: The Pose struct (position and orientation) - always present with zero values when not set
- is_valid: Whether the head pose data is valid
- timestamp: Timestamp struct with device and common time - always present

Note: Python code should only READ this data (created by C++ trackers), not modify it.
"""

from isaacteleop.schema import HeadPoseT


class TestHeadPoseTConstruction:
    """Tests for HeadPoseT construction and basic properties."""

    def test_default_construction(self):
        """Test default construction creates HeadPoseT with zero-initialized fields."""
        head_pose = HeadPoseT()

        assert head_pose is not None
        assert head_pose.pose.position.x == 0.0
        assert head_pose.is_valid is False
        assert head_pose.timestamp.device_time == 0


class TestHeadPoseTRepr:
    """Tests for HeadPoseT __repr__ method."""

    def test_repr(self):
        """Test __repr__ returns a meaningful string."""
        head_pose = HeadPoseT()

        repr_str = repr(head_pose)
        assert "HeadPoseT" in repr_str
