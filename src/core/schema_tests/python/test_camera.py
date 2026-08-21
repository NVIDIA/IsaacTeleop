# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for StreamType and FrameMetadataOak types in isaacteleop.schema.

Tests the following FlatBuffers types:
- StreamType: Enum identifying the OAK camera stream
- FrameMetadataOak: Table with stream and sequence_number
- FrameMetadataOakRecord: Record wrapper carrying DeviceDataTimestamp

Timestamps are carried by FrameMetadataOakRecord, not FrameMetadataOak.
"""

from isaacteleop.schema import (
    StreamType,
    FrameMetadataOak,
    FrameMetadataOakRecord,
    DeviceDataTimestamp,
)


class TestStreamTypeEnum:
    """Tests for StreamType enum."""

    def test_enum_values(self):
        assert StreamType.Color.value == 0
        assert StreamType.MonoLeft.value == 1
        assert StreamType.MonoRight.value == 2

    def test_enum_names(self):
        assert StreamType.Color.name == "Color"
        assert StreamType.MonoLeft.name == "MonoLeft"
        assert StreamType.MonoRight.name == "MonoRight"


class TestFrameMetadataOakConstruction:
    """Tests for FrameMetadataOak table construction."""

    def test_default_construction(self):
        metadata = FrameMetadataOak()

        assert metadata.stream == StreamType.Color
        assert metadata.sequence_number == 0

    def test_repr(self):
        metadata = FrameMetadataOak()
        repr_str = repr(metadata)

        assert "FrameMetadataOak" in repr_str


class TestFrameMetadataOakStream:
    """Tests that the stream field round-trips through the encoding."""

    def test_stream_color(self):
        assert FrameMetadataOak(stream=StreamType.Color).stream == StreamType.Color

    def test_stream_mono_left(self):
        assert (
            FrameMetadataOak(stream=StreamType.MonoLeft).stream == StreamType.MonoLeft
        )

    def test_stream_mono_right(self):
        assert (
            FrameMetadataOak(stream=StreamType.MonoRight).stream == StreamType.MonoRight
        )

    def test_each_encoding_is_independent(self):
        left = FrameMetadataOak(stream=StreamType.MonoLeft)
        right = FrameMetadataOak(stream=StreamType.MonoRight)
        assert left.stream == StreamType.MonoLeft
        assert right.stream == StreamType.MonoRight


class TestFrameMetadataOakSequenceNumber:
    """Tests for FrameMetadataOak sequence_number property."""

    def test_default_sequence_number(self):
        metadata = FrameMetadataOak()
        assert metadata.sequence_number == 0

    def test_sequence_number(self):
        assert FrameMetadataOak(sequence_number=42).sequence_number == 42

    def test_large_sequence_number(self):
        metadata = FrameMetadataOak(sequence_number=2**64 - 1)
        assert metadata.sequence_number == 2**64 - 1


class TestFrameMetadataOakCombined:
    """Tests for FrameMetadataOak with multiple fields set."""

    def test_full_metadata(self):
        metadata = FrameMetadataOak(stream=StreamType.MonoLeft, sequence_number=99)

        assert metadata.stream == StreamType.MonoLeft
        assert metadata.sequence_number == 99


class TestFrameMetadataOakScenarios:
    """Tests for realistic OAK frame metadata scenarios."""

    def test_first_frame(self):
        metadata = FrameMetadataOak(stream=StreamType.Color, sequence_number=0)

        assert metadata.stream == StreamType.Color
        assert metadata.sequence_number == 0

    def test_multi_stream(self):
        streams = [StreamType.Color, StreamType.MonoLeft, StreamType.MonoRight]
        for stream in streams:
            metadata = FrameMetadataOak(stream=stream, sequence_number=5)

            assert metadata.stream == stream

    def test_streaming_with_sequence_numbers(self):
        for i in range(5):
            metadata = FrameMetadataOak(stream=StreamType.Color, sequence_number=i)

            assert metadata.stream == StreamType.Color
            assert metadata.sequence_number == i


class TestFrameMetadataOakEdgeCases:
    """Edge case tests for FrameMetadataOak table."""

    def test_zero_and_max_sequence_numbers_encode(self):
        assert FrameMetadataOak(sequence_number=0).sequence_number == 0
        assert FrameMetadataOak(sequence_number=2**64 - 1).sequence_number == 2**64 - 1

    def test_repr_with_all_fields(self):
        metadata = FrameMetadataOak(stream=StreamType.MonoRight, sequence_number=7)
        repr_str = repr(metadata)

        assert "FrameMetadataOak" in repr_str
        assert "MonoRight" in repr_str


class TestFrameMetadataOakRecordTimestamp:
    """Tests for FrameMetadataOakRecord with DeviceDataTimestamp."""

    def test_construction_with_timestamp(self):
        """Test FrameMetadataOakRecord carries DeviceDataTimestamp."""
        data = FrameMetadataOak(stream=StreamType.MonoLeft, sequence_number=42)
        ts = DeviceDataTimestamp(1000000000, 2000000000, 3000000000)
        record = FrameMetadataOakRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 1000000000
        assert record.timestamp.sample_time_local_common_clock == 2000000000
        assert record.timestamp.sample_time_raw_device_clock == 3000000000
        assert record.data.stream == StreamType.MonoLeft
        assert record.data.sequence_number == 42

    def test_payload_less_record(self):
        """A record may carry a timestamp and no payload: MCAP's frame sentinel."""
        record = FrameMetadataOakRecord(None, DeviceDataTimestamp(1, 2, 3))
        assert record.data is None
        assert record.timestamp.available_time_local_common_clock == 1

    def test_timestamp_fields(self):
        """Test all three DeviceDataTimestamp fields are accessible."""
        data = FrameMetadataOak()
        ts = DeviceDataTimestamp(111, 222, 333)
        record = FrameMetadataOakRecord(data, ts)

        assert record.timestamp.available_time_local_common_clock == 111
        assert record.timestamp.sample_time_local_common_clock == 222
        assert record.timestamp.sample_time_raw_device_clock == 333
