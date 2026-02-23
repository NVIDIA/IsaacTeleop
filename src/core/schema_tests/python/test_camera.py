# SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for FrameMetadata type in isaacteleop.schema.

Tests the following FlatBuffers types:
- FrameMetadata: Table with sequence_number
"""

from isaacteleop.schema import FrameMetadata


class TestFrameMetadataConstruction:
    """Tests for FrameMetadata table construction."""

    def test_default_construction(self):
        """Test default construction creates FrameMetadata with None/zero fields."""
        metadata = FrameMetadata()

        assert metadata.sequence_number == 0

    def test_repr(self):
        """Test __repr__ returns meaningful string."""
        metadata = FrameMetadata()
        repr_str = repr(metadata)

        assert "FrameMetadata" in repr_str


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
        metadata.sequence_number = 100

        assert metadata.sequence_number == 100


class TestFrameMetadataScenarios:
    """Tests for realistic OAK frame metadata scenarios."""

    def test_first_frame(self):
        """Test metadata for the first captured frame."""
        metadata = FrameMetadata()
        metadata.sequence_number = 0

        assert metadata.sequence_number == 0

    def test_streaming_frames(self):
        """Test metadata for sequential streaming frames."""
        frames = []
        for i in range(5):
            metadata = FrameMetadata()
            metadata.sequence_number = i
            frames.append(metadata)

        # Verify sequential sequence numbers.
        for i, frame in enumerate(frames):
            assert frame.sequence_number == i

    def test_high_frequency_capture(self):
        """Test metadata for high-frequency capture (e.g., 120 FPS)."""
        metadata = FrameMetadata()
        metadata.sequence_number = 1

        assert metadata.sequence_number == 1

    def test_sequence_rollover_scenario(self):
        """Test metadata near sequence number boundaries."""
        metadata = FrameMetadata()
        metadata.sequence_number = 2147483646  # Near max int32

        assert metadata.sequence_number == 2147483646

        # Increment to max.
        metadata.sequence_number = 2147483647
        assert metadata.sequence_number == 2147483647


class TestFrameMetadataEdgeCases:
    """Edge case tests for FrameMetadata table."""

    def test_overwrite_sequence_number(self):
        """Test overwriting sequence number."""
        metadata = FrameMetadata()
        metadata.sequence_number = 10
        metadata.sequence_number = 20

        assert metadata.sequence_number == 20

    def test_repr_with_sequence_number(self):
        """Test __repr__ with sequence_number set."""
        metadata = FrameMetadata()
        metadata.sequence_number = 789
        repr_str = repr(metadata)

        assert "FrameMetadata" in repr_str
        assert "sequence_number" in repr_str

    def test_repr_with_default(self):
        """Test __repr__ with default values."""
        metadata = FrameMetadata()
        metadata.sequence_number = 42
        repr_str = repr(metadata)

        assert "FrameMetadata" in repr_str
