# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for FrameMetadata type in isaacteleop.schema.

Tests the following FlatBuffers types:
- FrameMetadata: Table with timestamp and sequence_number
"""

import pytest

from isaacteleop.schema import (
    FrameMetadata,
    Timestamp,
)


class TestFrameMetadataConstruction:
    """Tests for FrameMetadata table construction."""

    def test_default_construction(self):
        """Test default construction creates FrameMetadata with None/zero fields."""
        metadata = FrameMetadata()

        assert metadata.timestamp is None
        assert metadata.sequence_number == 0

    def test_repr(self):
        """Test __repr__ returns meaningful string."""
        metadata = FrameMetadata()
        repr_str = repr(metadata)

        assert "FrameMetadata" in repr_str


class TestFrameMetadataTimestamp:
    """Tests for FrameMetadata timestamp property."""

    def test_set_timestamp(self):
        """Test setting timestamp."""
        metadata = FrameMetadata()
        timestamp = Timestamp(device_time=1000000000, common_time=2000000000)
        metadata.timestamp = timestamp

        assert metadata.timestamp is not None
        assert metadata.timestamp.device_time == 1000000000
        assert metadata.timestamp.common_time == 2000000000

    def test_large_timestamp_values(self):
        """Test with large int64 timestamp values."""
        metadata = FrameMetadata()
        max_int64 = 9223372036854775807
        timestamp = Timestamp(device_time=max_int64, common_time=max_int64 - 1000)
        metadata.timestamp = timestamp

        assert metadata.timestamp.device_time == max_int64
        assert metadata.timestamp.common_time == max_int64 - 1000


class TestFrameMetadataSequenceNumber:
    """Tests for FrameMetadata sequence_number property."""

    def test_set_sequence_number(self):
        """Test setting sequence number."""
        metadata = FrameMetadata()
        metadata.sequence_number = 42

        assert metadata.sequence_number == 42

    def test_set_large_sequence_number(self):
        """Test setting large sequence number."""
        metadata = FrameMetadata()
        metadata.sequence_number = 2147483647  # Max int32

        assert metadata.sequence_number == 2147483647

    def test_set_negative_sequence_number(self):
        """Test setting negative sequence number (edge case)."""
        metadata = FrameMetadata()
        metadata.sequence_number = -1

        assert metadata.sequence_number == -1

    def test_increment_sequence_number(self):
        """Test incrementing sequence number."""
        metadata = FrameMetadata()
        metadata.sequence_number = 0
        metadata.sequence_number = metadata.sequence_number + 1

        assert metadata.sequence_number == 1


class TestFrameMetadataCombined:
    """Tests for FrameMetadata with multiple fields set."""

    def test_full_metadata(self):
        """Test with all fields set."""
        metadata = FrameMetadata()
        metadata.timestamp = Timestamp(device_time=1000, common_time=2000)
        metadata.sequence_number = 100

        assert metadata.timestamp is not None
        assert metadata.timestamp.device_time == 1000
        assert metadata.timestamp.common_time == 2000
        assert metadata.sequence_number == 100


class TestFrameMetadataScenarios:
    """Tests for realistic OAK frame metadata scenarios."""

    def test_first_frame(self):
        """Test metadata for the first captured frame."""
        metadata = FrameMetadata()
        metadata.timestamp = Timestamp(device_time=0, common_time=1000000)
        metadata.sequence_number = 0

        assert metadata.sequence_number == 0
        assert metadata.timestamp.device_time == 0

    def test_streaming_frames(self):
        """Test metadata for sequential streaming frames."""
        frames = []
        base_device_time = 1000000000  # 1 second in nanoseconds.
        frame_interval = 33333333  # ~30 FPS in nanoseconds.

        for i in range(5):
            metadata = FrameMetadata()
            metadata.timestamp = Timestamp(
                device_time=base_device_time + i * frame_interval,
                common_time=base_device_time + i * frame_interval + 100,  # Small offset.
            )
            metadata.sequence_number = i
            frames.append(metadata)

        # Verify sequential sequence numbers.
        for i, frame in enumerate(frames):
            assert frame.sequence_number == i

        # Verify timestamps are increasing.
        for i in range(1, len(frames)):
            assert frames[i].timestamp.device_time > frames[i - 1].timestamp.device_time

    def test_high_frequency_capture(self):
        """Test metadata for high-frequency capture (e.g., 120 FPS)."""
        metadata = FrameMetadata()
        metadata.timestamp = Timestamp(
            device_time=8333333,  # ~8.3ms (120 FPS interval)
            common_time=8333400,
        )
        metadata.sequence_number = 1

        assert metadata.sequence_number == 1

    def test_sequence_rollover_scenario(self):
        """Test metadata near sequence number boundaries."""
        metadata = FrameMetadata()
        metadata.timestamp = Timestamp(device_time=999999999999, common_time=999999999999)
        metadata.sequence_number = 2147483646  # Near max int32

        assert metadata.sequence_number == 2147483646

        # Increment to max.
        metadata.sequence_number = 2147483647
        assert metadata.sequence_number == 2147483647


class TestFrameMetadataEdgeCases:
    """Edge case tests for FrameMetadata table."""

    def test_zero_timestamp(self):
        """Test with zero timestamp values."""
        metadata = FrameMetadata()
        metadata.timestamp = Timestamp(device_time=0, common_time=0)

        assert metadata.timestamp.device_time == 0
        assert metadata.timestamp.common_time == 0

    def test_negative_timestamp(self):
        """Test with negative timestamp values (valid for relative times)."""
        metadata = FrameMetadata()
        metadata.timestamp = Timestamp(device_time=-1000, common_time=-2000)

        assert metadata.timestamp.device_time == -1000
        assert metadata.timestamp.common_time == -2000

    def test_overwrite_sequence_number(self):
        """Test overwriting sequence number."""
        metadata = FrameMetadata()
        metadata.sequence_number = 10
        metadata.sequence_number = 20

        assert metadata.sequence_number == 20

    def test_overwrite_timestamp(self):
        """Test overwriting timestamp."""
        metadata = FrameMetadata()
        metadata.timestamp = Timestamp(device_time=100, common_time=200)
        metadata.timestamp = Timestamp(device_time=300, common_time=400)

        assert metadata.timestamp.device_time == 300
        assert metadata.timestamp.common_time == 400

    def test_repr_with_timestamp(self):
        """Test __repr__ with timestamp set."""
        metadata = FrameMetadata()
        metadata.timestamp = Timestamp(device_time=123, common_time=456)
        metadata.sequence_number = 789
        repr_str = repr(metadata)

        assert "FrameMetadata" in repr_str
        assert "timestamp" in repr_str
        assert "sequence_number" in repr_str

    def test_repr_without_timestamp(self):
        """Test __repr__ without timestamp set."""
        metadata = FrameMetadata()
        metadata.sequence_number = 42
        repr_str = repr(metadata)

        assert "FrameMetadata" in repr_str
        assert "None" in repr_str or "timestamp" in repr_str
