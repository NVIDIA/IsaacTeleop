// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated OAK FlatBuffer types.

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/oak_generated.h>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs for FrameMetadata table.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2

static_assert(core::FrameMetadata::VT_TIMESTAMP == VT(0));
static_assert(core::FrameMetadata::VT_SEQUENCE_NUMBER == VT(1));

// =============================================================================
// FrameMetadataT Tests (table native type)
// =============================================================================
TEST_CASE("FrameMetadataT default construction", "[camera][native]")
{
    core::FrameMetadataT metadata;

    // Timestamp pointer should be null by default.
    CHECK(metadata.timestamp == nullptr);
    // Integer field should be zero by default.
    CHECK(metadata.sequence_number == 0);
}

TEST_CASE("FrameMetadataT can store timestamp", "[camera][native]")
{
    core::FrameMetadataT metadata;

    // Create timestamp.
    metadata.timestamp = std::make_unique<core::Timestamp>(1000000000, 2000000000);

    CHECK(metadata.timestamp != nullptr);
    CHECK(metadata.timestamp->device_time() == 1000000000);
    CHECK(metadata.timestamp->common_time() == 2000000000);
}

TEST_CASE("FrameMetadataT can store sequence number", "[camera][native]")
{
    core::FrameMetadataT metadata;

    metadata.sequence_number = 42;

    CHECK(metadata.sequence_number == 42);
}

TEST_CASE("FrameMetadataT can store full metadata", "[camera][native]")
{
    core::FrameMetadataT metadata;

    // Set all fields.
    metadata.timestamp = std::make_unique<core::Timestamp>(3000000000, 4000000000);
    metadata.sequence_number = 100;

    CHECK(metadata.timestamp != nullptr);
    CHECK(metadata.timestamp->device_time() == 3000000000);
    CHECK(metadata.timestamp->common_time() == 4000000000);
    CHECK(metadata.sequence_number == 100);
}

// =============================================================================
// FrameMetadata Serialization Tests
// =============================================================================
TEST_CASE("FrameMetadata serialization and deserialization", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create native object.
    core::FrameMetadataT metadata;
    metadata.timestamp = std::make_unique<core::Timestamp>(1234567890, 9876543210);
    metadata.sequence_number = 999;

    // Serialize.
    auto offset = core::FrameMetadata::Pack(builder, &metadata);
    builder.Finish(offset);

    // Deserialize.
    auto* deserialized = flatbuffers::GetRoot<core::FrameMetadata>(builder.GetBufferPointer());

    // Verify timestamp.
    REQUIRE(deserialized->timestamp() != nullptr);
    CHECK(deserialized->timestamp()->device_time() == 1234567890);
    CHECK(deserialized->timestamp()->common_time() == 9876543210);

    // Verify sequence number.
    CHECK(deserialized->sequence_number() == 999);
}

TEST_CASE("FrameMetadata can be unpacked from buffer", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create native object with minimal data.
    core::FrameMetadataT metadata;
    metadata.timestamp = std::make_unique<core::Timestamp>(100, 200);
    metadata.sequence_number = 5;

    // Serialize.
    auto offset = core::FrameMetadata::Pack(builder, &metadata);
    builder.Finish(offset);

    // Deserialize to table.
    auto* table = flatbuffers::GetRoot<core::FrameMetadata>(builder.GetBufferPointer());

    // Unpack to native.
    auto unpacked = std::make_unique<core::FrameMetadataT>();
    table->UnPackTo(unpacked.get());

    // Verify.
    REQUIRE(unpacked->timestamp != nullptr);
    CHECK(unpacked->timestamp->device_time() == 100);
    CHECK(unpacked->timestamp->common_time() == 200);
    CHECK(unpacked->sequence_number == 5);
}

TEST_CASE("FrameMetadata without timestamp", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::FrameMetadataT metadata;
    // timestamp is intentionally left null.
    metadata.sequence_number = 123;

    auto offset = core::FrameMetadata::Pack(builder, &metadata);
    builder.Finish(offset);

    auto* deserialized = flatbuffers::GetRoot<core::FrameMetadata>(builder.GetBufferPointer());

    CHECK(deserialized->timestamp() == nullptr);
    CHECK(deserialized->sequence_number() == 123);
}

// =============================================================================
// Realistic Camera Frame Scenarios
// =============================================================================
TEST_CASE("FrameMetadata first frame", "[camera][scenario]")
{
    core::FrameMetadataT metadata;
    metadata.timestamp = std::make_unique<core::Timestamp>(0, 1000000);
    metadata.sequence_number = 0;

    CHECK(metadata.sequence_number == 0);
    CHECK(metadata.timestamp->device_time() == 0);
}

TEST_CASE("FrameMetadata streaming frames at 30 FPS", "[camera][scenario]")
{
    // Simulate 5 frames at 30 FPS (33.33ms interval = 33333333 ns).
    constexpr int64_t base_time = 1000000000;
    constexpr int64_t frame_interval = 33333333;

    for (int i = 0; i < 5; ++i)
    {
        core::FrameMetadataT metadata;
        metadata.timestamp = std::make_unique<core::Timestamp>(base_time + i * frame_interval,
                                                               base_time + i * frame_interval + 100 // Small offset for
                                                                                                    // common_time.
        );
        metadata.sequence_number = i;

        CHECK(metadata.sequence_number == i);
        CHECK(metadata.timestamp->device_time() == base_time + i * frame_interval);
    }
}

TEST_CASE("FrameMetadata high frequency capture at 120 FPS", "[camera][scenario]")
{
    // 120 FPS = 8.33ms interval = 8333333 ns.
    core::FrameMetadataT metadata;
    metadata.timestamp = std::make_unique<core::Timestamp>(8333333, 8333400);
    metadata.sequence_number = 1;

    CHECK(metadata.sequence_number == 1);
    CHECK(metadata.timestamp->device_time() == 8333333);
}

TEST_CASE("FrameMetadata sequence rollover scenario", "[camera][scenario]")
{
    // Test near max int32 boundary.
    core::FrameMetadataT metadata;
    metadata.timestamp = std::make_unique<core::Timestamp>(999999999999, 999999999999);
    metadata.sequence_number = 2147483646; // Near max int32.

    CHECK(metadata.sequence_number == 2147483646);

    // Increment to max.
    metadata.sequence_number = 2147483647;
    CHECK(metadata.sequence_number == 2147483647);
}

// =============================================================================
// Edge Cases
// =============================================================================
TEST_CASE("FrameMetadata with negative sequence number", "[camera][edge]")
{
    // Although sequence numbers are typically positive, test negative values.
    core::FrameMetadataT metadata;
    metadata.sequence_number = -1;

    CHECK(metadata.sequence_number == -1);
}

TEST_CASE("FrameMetadata with zero timestamp", "[camera][edge]")
{
    core::FrameMetadataT metadata;
    metadata.timestamp = std::make_unique<core::Timestamp>(0, 0);
    metadata.sequence_number = 0;

    CHECK(metadata.timestamp->device_time() == 0);
    CHECK(metadata.timestamp->common_time() == 0);
}

TEST_CASE("FrameMetadata with negative timestamp", "[camera][edge]")
{
    // Test with negative timestamp values (valid for relative times).
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
    metadata.sequence_number = 1;

    CHECK(metadata.timestamp->device_time() == max_int64);
    CHECK(metadata.timestamp->common_time() == max_int64 - 1000);
}

TEST_CASE("FrameMetadata with max int32 sequence number", "[camera][edge]")
{
    core::FrameMetadataT metadata;
    metadata.sequence_number = 2147483647; // Max int32.

    CHECK(metadata.sequence_number == 2147483647);
}

TEST_CASE("FrameMetadata with min int32 sequence number", "[camera][edge]")
{
    core::FrameMetadataT metadata;
    metadata.sequence_number = -2147483648; // Min int32.

    CHECK(metadata.sequence_number == -2147483648);
}

TEST_CASE("FrameMetadata buffer size is reasonable", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::FrameMetadataT metadata;
    metadata.timestamp = std::make_unique<core::Timestamp>(0, 0);
    metadata.sequence_number = 0;

    auto offset = core::FrameMetadata::Pack(builder, &metadata);
    builder.Finish(offset);

    // Buffer should be reasonably small (under 100 bytes for this simple message).
    CHECK(builder.GetSize() < 100);
}

TEST_CASE("FrameMetadata can update sequence number", "[camera][native]")
{
    core::FrameMetadataT metadata;
    metadata.sequence_number = 0;

    // Simulate frame counter increment.
    for (int i = 1; i <= 10; ++i)
    {
        metadata.sequence_number = i;
        CHECK(metadata.sequence_number == i);
    }
}

TEST_CASE("FrameMetadata can update timestamp", "[camera][native]")
{
    core::FrameMetadataT metadata;

    // Set initial timestamp.
    metadata.timestamp = std::make_unique<core::Timestamp>(100, 200);
    CHECK(metadata.timestamp->device_time() == 100);

    // Update timestamp.
    metadata.timestamp = std::make_unique<core::Timestamp>(300, 400);
    CHECK(metadata.timestamp->device_time() == 300);
    CHECK(metadata.timestamp->common_time() == 400);
}

TEST_CASE("FrameMetadata roundtrip preserves all data", "[camera][scenario]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create comprehensive metadata.
    core::FrameMetadataT original;
    original.timestamp = std::make_unique<core::Timestamp>(5555555555, 6666666666);
    original.sequence_number = 12345;

    // Serialize.
    auto offset = core::FrameMetadata::Pack(builder, &original);
    builder.Finish(offset);

    // Unpack to new object.
    auto* table = flatbuffers::GetRoot<core::FrameMetadata>(builder.GetBufferPointer());
    core::FrameMetadataT roundtrip;
    table->UnPackTo(&roundtrip);

    // Verify all data preserved.
    REQUIRE(roundtrip.timestamp != nullptr);
    CHECK(roundtrip.timestamp->device_time() == 5555555555);
    CHECK(roundtrip.timestamp->common_time() == 6666666666);
    CHECK(roundtrip.sequence_number == 12345);
}
