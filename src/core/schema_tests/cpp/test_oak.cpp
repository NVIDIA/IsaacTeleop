// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated OAK FlatBuffer types.

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/oak_generated.h>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2

static_assert(core::FrameMetadata::VT_STREAM == VT(0));
static_assert(core::FrameMetadata::VT_TIMESTAMP == VT(1));
static_assert(core::FrameMetadata::VT_SEQUENCE_NUMBER == VT(2));

// =============================================================================
// StreamType Enum Tests
// =============================================================================
TEST_CASE("StreamType enum values", "[camera][enum]")
{
    CHECK(core::StreamType_Color == 0);
    CHECK(core::StreamType_MonoLeft == 1);
    CHECK(core::StreamType_MonoRight == 2);
}

TEST_CASE("StreamType enum name lookup", "[camera][enum]")
{
    CHECK(std::string(core::EnumNameStreamType(core::StreamType_Color)) == "Color");
    CHECK(std::string(core::EnumNameStreamType(core::StreamType_MonoLeft)) == "MonoLeft");
    CHECK(std::string(core::EnumNameStreamType(core::StreamType_MonoRight)) == "MonoRight");
}

// =============================================================================
// FrameMetadataT Tests (table native type)
// =============================================================================
TEST_CASE("FrameMetadataT default construction", "[camera][native]")
{
    core::FrameMetadataT metadata;

    CHECK(metadata.stream == core::StreamType_Color);
    CHECK(metadata.timestamp == nullptr);
    CHECK(metadata.sequence_number == 0);
}

TEST_CASE("FrameMetadataT can store all fields", "[camera][native]")
{
    core::FrameMetadataT metadata;
    metadata.stream = core::StreamType_MonoLeft;
    metadata.timestamp = std::make_unique<core::Timestamp>(1000000000, 2000000000);
    metadata.sequence_number = 42;

    CHECK(metadata.stream == core::StreamType_MonoLeft);
    REQUIRE(metadata.timestamp != nullptr);
    CHECK(metadata.timestamp->device_time() == 1000000000);
    CHECK(metadata.timestamp->common_time() == 2000000000);
    CHECK(metadata.sequence_number == 42);
}

// =============================================================================
// Serialization Tests
// =============================================================================
TEST_CASE("FrameMetadata serialization and deserialization", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::FrameMetadataT metadata;
    metadata.stream = core::StreamType_MonoRight;
    metadata.timestamp = std::make_unique<core::Timestamp>(1234567890, 9876543210);
    metadata.sequence_number = 10;

    auto offset = core::FrameMetadata::Pack(builder, &metadata);
    builder.Finish(offset);

    auto* deserialized = flatbuffers::GetRoot<core::FrameMetadata>(builder.GetBufferPointer());

    REQUIRE(deserialized->timestamp() != nullptr);
    CHECK(deserialized->timestamp()->device_time() == 1234567890);
    CHECK(deserialized->timestamp()->common_time() == 9876543210);
    CHECK(deserialized->stream() == core::StreamType_MonoRight);
    CHECK(deserialized->sequence_number() == 10);
}

TEST_CASE("FrameMetadata roundtrip preserves all data", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::FrameMetadataT original;
    original.stream = core::StreamType_Color;
    original.timestamp = std::make_unique<core::Timestamp>(5555555555, 6666666666);
    original.sequence_number = 99;

    auto offset = core::FrameMetadata::Pack(builder, &original);
    builder.Finish(offset);

    auto* table = flatbuffers::GetRoot<core::FrameMetadata>(builder.GetBufferPointer());
    core::FrameMetadataT roundtrip;
    table->UnPackTo(&roundtrip);

    CHECK(roundtrip.stream == core::StreamType_Color);
    REQUIRE(roundtrip.timestamp != nullptr);
    CHECK(roundtrip.timestamp->device_time() == 5555555555);
    CHECK(roundtrip.timestamp->common_time() == 6666666666);
    CHECK(roundtrip.sequence_number == 99);
}

TEST_CASE("FrameMetadata without timestamp", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::FrameMetadataT metadata;
    metadata.stream = core::StreamType_MonoLeft;
    metadata.sequence_number = 7;

    auto offset = core::FrameMetadata::Pack(builder, &metadata);
    builder.Finish(offset);

    auto* deserialized = flatbuffers::GetRoot<core::FrameMetadata>(builder.GetBufferPointer());

    CHECK(deserialized->timestamp() == nullptr);
    CHECK(deserialized->stream() == core::StreamType_MonoLeft);
    CHECK(deserialized->sequence_number() == 7);
}

TEST_CASE("FrameMetadata buffer size is reasonable", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::FrameMetadataT metadata;
    metadata.stream = core::StreamType_Color;
    metadata.timestamp = std::make_unique<core::Timestamp>(0, 0);
    metadata.sequence_number = 0;

    auto offset = core::FrameMetadata::Pack(builder, &metadata);
    builder.Finish(offset);

    CHECK(builder.GetSize() < 100);
}

// =============================================================================
// Realistic Scenarios
// =============================================================================
TEST_CASE("FrameMetadata streaming at 30 FPS with sequence numbers", "[camera][scenario]")
{
    constexpr int64_t base_time = 1000000000;
    constexpr int64_t frame_interval = 33333333;

    for (int i = 0; i < 5; ++i)
    {
        core::FrameMetadataT metadata;
        metadata.stream = core::StreamType_Color;
        metadata.timestamp =
            std::make_unique<core::Timestamp>(base_time + i * frame_interval, base_time + i * frame_interval + 100);
        metadata.sequence_number = static_cast<uint64_t>(i);

        CHECK(metadata.sequence_number == static_cast<uint64_t>(i));
        CHECK(metadata.timestamp->device_time() == base_time + i * frame_interval);
    }
}

// =============================================================================
// Edge Cases
// =============================================================================
TEST_CASE("FrameMetadata with large sequence number", "[camera][edge]")
{
    core::FrameMetadataT metadata;
    metadata.sequence_number = UINT64_MAX;

    CHECK(metadata.sequence_number == UINT64_MAX);
}

TEST_CASE("FrameMetadata with zero timestamp", "[camera][edge]")
{
    core::FrameMetadataT metadata;
    metadata.timestamp = std::make_unique<core::Timestamp>(0, 0);

    CHECK(metadata.timestamp->device_time() == 0);
    CHECK(metadata.timestamp->common_time() == 0);
}

TEST_CASE("FrameMetadata with negative timestamp", "[camera][edge]")
{
    core::FrameMetadataT metadata;
    metadata.timestamp = std::make_unique<core::Timestamp>(-1000, -2000);

    CHECK(metadata.timestamp->device_time() == -1000);
    CHECK(metadata.timestamp->common_time() == -2000);
}

TEST_CASE("FrameMetadata with large timestamp values", "[camera][edge]")
{
    core::FrameMetadataT metadata;
    int64_t max_int64 = 9223372036854775807;
    metadata.timestamp = std::make_unique<core::Timestamp>(max_int64, max_int64 - 1000);

    CHECK(metadata.timestamp->device_time() == max_int64);
    CHECK(metadata.timestamp->common_time() == max_int64 - 1000);
}

TEST_CASE("FrameMetadata can update timestamp", "[camera][native]")
{
    core::FrameMetadataT metadata;

    metadata.timestamp = std::make_unique<core::Timestamp>(100, 200);
    CHECK(metadata.timestamp->device_time() == 100);

    metadata.timestamp = std::make_unique<core::Timestamp>(300, 400);
    CHECK(metadata.timestamp->device_time() == 300);
    CHECK(metadata.timestamp->common_time() == 400);
}
