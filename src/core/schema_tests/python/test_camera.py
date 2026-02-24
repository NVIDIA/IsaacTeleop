# SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
# SPDX-License-Identifier: Apache-2.0

"""Unit tests for StreamType and FrameMetadataOak types in isaacteleop.schema.

Tests the following FlatBuffers types:
- StreamType: Enum identifying the OAK camera stream
- FrameMetadataOak: Table with stream, timestamp, and sequence_number
"""

from isaacteleop.schema import (
    StreamType,
    FrameMetadataOak,
    Timestamp,
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

        assert metadata.timestamp is None
        assert metadata.stream == StreamType.Color
        assert metadata.sequence_number == 0

    def test_repr(self):
        metadata = FrameMetadataOak()
        repr_str = repr(metadata)

        assert "FrameMetadataOak" in repr_str


class TestFrameMetadataOakTimestamp:
    """Tests for FrameMetadataOak timestamp property."""

    def test_set_timestamp(self):
        metadata = FrameMetadataOak()
        timestamp = Timestamp(device_time=1000000000, common_time=2000000000)
        metadata.timestamp = timestamp

        assert metadata.timestamp is not None
        assert metadata.timestamp.device_time == 1000000000
        assert metadata.timestamp.common_time == 2000000000

    def test_large_timestamp_values(self):
        metadata = FrameMetadataOak()
        max_int64 = 9223372036854775807
        timestamp = Timestamp(device_time=max_int64, common_time=max_int64 - 1000)
        metadata.timestamp = timestamp

        assert metadata.timestamp.device_time == max_int64
        assert metadata.timestamp.common_time == max_int64 - 1000


class TestFrameMetadataOakStream:
    """Tests for FrameMetadataOak stream property."""

    def test_set_stream_color(self):
        metadata = FrameMetadataOak()
        metadata.stream = StreamType.Color
        assert metadata.stream == StreamType.Color

    def test_set_stream_mono_left(self):
        metadata = FrameMetadataOak()
        metadata.stream = StreamType.MonoLeft
        assert metadata.stream == StreamType.MonoLeft

    def test_set_stream_mono_right(self):
        metadata = FrameMetadataOak()
        metadata.stream = StreamType.MonoRight
        assert metadata.stream == StreamType.MonoRight

    def test_overwrite_stream(self):
        metadata = FrameMetadataOak()
        metadata.stream = StreamType.MonoLeft
        metadata.stream = StreamType.MonoRight
        assert metadata.stream == StreamType.MonoRight


class TestFrameMetadataOakSequenceNumber:
    """Tests for FrameMetadataOak sequence_number property."""

    def test_default_sequence_number(self):
        metadata = FrameMetadataOak()
        assert metadata.sequence_number == 0

    def test_set_sequence_number(self):
        metadata = FrameMetadataOak()
        metadata.sequence_number = 42
        assert metadata.sequence_number == 42

    def test_large_sequence_number(self):
        metadata = FrameMetadataOak()
        metadata.sequence_number = 2**64 - 1
        assert metadata.sequence_number == 2**64 - 1


class TestFrameMetadataOakCombined:
    """Tests for FrameMetadataOak with multiple fields set."""

    def test_full_metadata(self):
        metadata = FrameMetadataOak()
        metadata.stream = StreamType.MonoLeft
        metadata.timestamp = Timestamp(device_time=1000, common_time=2000)
        metadata.sequence_number = 99

        assert metadata.stream == StreamType.MonoLeft
        assert metadata.timestamp.device_time == 1000
        assert metadata.timestamp.common_time == 2000
        assert metadata.sequence_number == 99


class TestFrameMetadataOakScenarios:
    """Tests for realistic OAK frame metadata scenarios."""

    def test_first_frame(self):
        metadata = FrameMetadataOak()
        metadata.timestamp = Timestamp(device_time=0, common_time=1000000)
        metadata.stream = StreamType.Color
        metadata.sequence_number = 0

        assert metadata.stream == StreamType.Color
        assert metadata.timestamp.device_time == 0
        assert metadata.sequence_number == 0

    def test_multi_stream(self):
        streams = [StreamType.Color, StreamType.MonoLeft, StreamType.MonoRight]
        for stream in streams:
            metadata = FrameMetadataOak()
            metadata.timestamp = Timestamp(
                device_time=1000000000, common_time=1000000100
            )
            metadata.stream = stream
            metadata.sequence_number = 5

            assert metadata.stream == stream

    def test_streaming_with_sequence_numbers(self):
        base_device_time = 1000000000
        frame_interval = 33333333

        for i in range(5):
            metadata = FrameMetadataOak()
            metadata.timestamp = Timestamp(
                device_time=base_device_time + i * frame_interval,
                common_time=base_device_time + i * frame_interval + 100,
            )
            metadata.stream = StreamType.Color
            metadata.sequence_number = i

            assert metadata.stream == StreamType.Color
            assert metadata.sequence_number == i
            assert (
                metadata.timestamp.device_time == base_device_time + i * frame_interval
            )


class TestFrameMetadataOakEdgeCases:
    """Edge case tests for FrameMetadataOak table."""

    def test_zero_timestamp(self):
        metadata = FrameMetadataOak()
        metadata.timestamp = Timestamp(device_time=0, common_time=0)
        assert metadata.timestamp.device_time == 0
        assert metadata.timestamp.common_time == 0

    def test_negative_timestamp(self):
        metadata = FrameMetadataOak()
        metadata.timestamp = Timestamp(device_time=-1000, common_time=-2000)
        assert metadata.timestamp.device_time == -1000
        assert metadata.timestamp.common_time == -2000

    def test_overwrite_timestamp(self):
        metadata = FrameMetadataOak()
        metadata.timestamp = Timestamp(device_time=100, common_time=200)
        metadata.timestamp = Timestamp(device_time=300, common_time=400)
        assert metadata.timestamp.device_time == 300
        assert metadata.timestamp.common_time == 400

    def test_repr_with_all_fields(self):
        metadata = FrameMetadataOak()
        metadata.timestamp = Timestamp(device_time=123, common_time=456)
        metadata.stream = StreamType.MonoRight
        metadata.sequence_number = 7
        repr_str = repr(metadata)

        assert "FrameMetadataOak" in repr_str
        assert "MonoRight" in repr_str

    def test_repr_without_timestamp(self):
        metadata = FrameMetadataOak()
        repr_str = repr(metadata)

        assert "FrameMetadataOak" in repr_str
        assert "None" in repr_str or "timestamp" in repr_str
