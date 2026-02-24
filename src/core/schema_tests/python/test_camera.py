# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for FrameMetadata type in isaacteleop.schema.

Tests the following FlatBuffers types:
- FrameMetadata: Struct (read-only) with timestamp and sequence_number
"""

from isaacteleop.schema import (
    FrameMetadata,
)


class TestFrameMetadataConstruction:
    """Tests for FrameMetadata struct construction."""

    def test_default_construction(self):
        """Test default construction creates FrameMetadata with zero-initialized fields."""
        metadata = FrameMetadata()

        assert metadata.timestamp.device_time == 0
        assert metadata.sequence_number == 0

    def test_repr(self):
        """Test __repr__ returns meaningful string."""
        metadata = FrameMetadata()
        repr_str = repr(metadata)

        assert "FrameMetadata" in repr_str
