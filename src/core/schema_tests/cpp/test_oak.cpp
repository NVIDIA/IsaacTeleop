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

static_assert(core::FrameMetadata::VT_SEQUENCE_NUMBER == VT(0));

// =============================================================================
// FrameMetadataT Tests (table native type)
// =============================================================================
TEST_CASE("FrameMetadataT default construction", "[camera][native]")
{
    core::FrameMetadataT metadata;

    // Integer field should be zero by default.
    CHECK(metadata.sequence_number == 0);
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
    metadata.sequence_number = 100;

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
    metadata.sequence_number = 999;

    core::FrameMetadataRecordT record;
    record.data = std::make_unique<core::FrameMetadataT>(metadata);
    record.timestamp = std::make_unique<core::DeviceDataTimestamp>(1234567890, 9876543210, 0);

    // Serialize.
    auto offset = core::FrameMetadataRecord::Pack(builder, &record);
    builder.Finish(offset);

    // Deserialize.
    auto* deserialized_record = flatbuffers::GetRoot<core::FrameMetadataRecord>(builder.GetBufferPointer());
    REQUIRE(deserialized_record->data() != nullptr);
    auto* deserialized = deserialized_record->data();

    // Verify sequence number.
    CHECK(deserialized->sequence_number() == 999);
}

TEST_CASE("FrameMetadata can be unpacked from buffer", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create native object with minimal data.
    core::FrameMetadataT metadata;
    metadata.sequence_number = 5;

    core::FrameMetadataRecordT record;
    record.data = std::make_unique<core::FrameMetadataT>(metadata);
    record.timestamp = std::make_unique<core::DeviceDataTimestamp>(100, 200, 0);

    // Serialize.
    auto offset = core::FrameMetadataRecord::Pack(builder, &record);
    builder.Finish(offset);

    // Deserialize to table.
    auto* record_table = flatbuffers::GetRoot<core::FrameMetadataRecord>(builder.GetBufferPointer());
    REQUIRE(record_table->data() != nullptr);

    // Unpack to native.
    auto unpacked = std::make_unique<core::FrameMetadataT>();
    record_table->data()->UnPackTo(unpacked.get());

    // Verify.
    CHECK(unpacked->sequence_number == 5);
}

TEST_CASE("FrameMetadataRecord without timestamp", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::FrameMetadataT metadata;
    metadata.sequence_number = 123;

    core::FrameMetadataRecordT record;
    record.data = std::make_unique<core::FrameMetadataT>(metadata);
    // timestamp is intentionally left null.

    auto offset = core::FrameMetadataRecord::Pack(builder, &record);
    builder.Finish(offset);

    auto* deserialized_record = flatbuffers::GetRoot<core::FrameMetadataRecord>(builder.GetBufferPointer());
    REQUIRE(deserialized_record->data() != nullptr);

    CHECK(deserialized_record->timestamp() == nullptr);
    CHECK(deserialized_record->data()->sequence_number() == 123);
}

// =============================================================================
// Realistic Camera Frame Scenarios
// =============================================================================
TEST_CASE("FrameMetadata first frame", "[camera][scenario]")
{
    core::FrameMetadataT metadata;
    metadata.sequence_number = 0;

    CHECK(metadata.sequence_number == 0);
}

TEST_CASE("FrameMetadata streaming frames at 30 FPS", "[camera][scenario]")
{
    // Simulate 5 frames at 30 FPS (33.33ms interval = 33333333 ns).
    constexpr int64_t base_time = 1000000000;
    constexpr int64_t frame_interval = 33333333;

    for (int i = 0; i < 5; ++i)
    {
        core::FrameMetadataT metadata;
        metadata.sequence_number = i;

        CHECK(metadata.sequence_number == i);
    }
}

TEST_CASE("FrameMetadata high frequency capture at 120 FPS", "[camera][scenario]")
{
    // 120 FPS = 8.33ms interval = 8333333 ns.
    core::FrameMetadataT metadata;
    metadata.sequence_number = 1;

    CHECK(metadata.sequence_number == 1);
}

TEST_CASE("FrameMetadata sequence rollover scenario", "[camera][scenario]")
{
    // Test near max int32 boundary.
    core::FrameMetadataT metadata;
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
    metadata.sequence_number = 0;

    core::FrameMetadataRecordT record;
    record.data = std::make_unique<core::FrameMetadataT>(metadata);
    record.timestamp = std::make_unique<core::DeviceDataTimestamp>(0, 0, 0);

    auto offset = core::FrameMetadataRecord::Pack(builder, &record);
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

TEST_CASE("FrameMetadata roundtrip preserves all data", "[camera][scenario]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create comprehensive metadata.
    core::FrameMetadataT original;
    original.sequence_number = 12345;

    core::FrameMetadataRecordT record;
    record.data = std::make_unique<core::FrameMetadataT>(original);
    record.timestamp = std::make_unique<core::DeviceDataTimestamp>(5555555555, 6666666666, 0);

    // Serialize.
    auto offset = core::FrameMetadataRecord::Pack(builder, &record);
    builder.Finish(offset);

    // Unpack to new object.
    auto* record_table = flatbuffers::GetRoot<core::FrameMetadataRecord>(builder.GetBufferPointer());
    REQUIRE(record_table->data() != nullptr);
    core::FrameMetadataT roundtrip;
    record_table->data()->UnPackTo(&roundtrip);

    // Verify all data preserved.
    CHECK(roundtrip.sequence_number == 12345);
}
