// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated OAK FlatBuffer types.

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/oak_generated.h>
#include <schema/timestamp_generated.h>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2

static_assert(core::FrameMetadataOak::VT_STREAM == VT(0));
static_assert(core::FrameMetadataOak::VT_SEQUENCE_NUMBER == VT(1));

static_assert(core::FrameMetadataOakRecord::VT_DATA == VT(0));
static_assert(core::FrameMetadataOakRecord::VT_TIMESTAMP == VT(1));

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
// FrameMetadataOakT Tests (table native type)
// =============================================================================
TEST_CASE("FrameMetadataOakT default construction", "[camera][native]")
{
    core::FrameMetadataOakT metadata;

    CHECK(metadata.stream == core::StreamType_Color);
    CHECK(metadata.sequence_number == 0);
}

TEST_CASE("FrameMetadataOakT can store all fields", "[camera][native]")
{
    core::FrameMetadataOakT metadata;
    metadata.stream = core::StreamType_MonoLeft;
    metadata.sequence_number = 42;

    CHECK(metadata.stream == core::StreamType_MonoLeft);
    CHECK(metadata.sequence_number == 42);
}


// =============================================================================
// Serialization Tests
// =============================================================================
TEST_CASE("FrameMetadataOak serialization and deserialization", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::FrameMetadataOakT metadata;
    metadata.stream = core::StreamType_MonoRight;
    metadata.sequence_number = 10;

    auto offset = core::FrameMetadataOak::Pack(builder, &metadata);
    builder.Finish(offset);

    auto* deserialized = flatbuffers::GetRoot<core::FrameMetadataOak>(builder.GetBufferPointer());

    CHECK(deserialized->stream() == core::StreamType_MonoRight);
    CHECK(deserialized->sequence_number() == 10);
}

TEST_CASE("FrameMetadataOak roundtrip preserves all data", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::FrameMetadataOakT original;
    original.stream = core::StreamType_Color;
    original.sequence_number = 99;

    auto offset = core::FrameMetadataOak::Pack(builder, &original);
    builder.Finish(offset);

    auto* table = flatbuffers::GetRoot<core::FrameMetadataOak>(builder.GetBufferPointer());
    core::FrameMetadataOakT roundtrip;
    table->UnPackTo(&roundtrip);

    CHECK(roundtrip.stream == core::StreamType_Color);
    CHECK(roundtrip.sequence_number == 99);
}

TEST_CASE("FrameMetadataOak buffer size is reasonable", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::FrameMetadataOakT metadata;
    metadata.stream = core::StreamType_Color;
    metadata.sequence_number = 0;

    auto offset = core::FrameMetadataOak::Pack(builder, &metadata);
    builder.Finish(offset);

    CHECK(builder.GetSize() < 100);
}

// =============================================================================
// Realistic Scenarios
// =============================================================================
TEST_CASE("FrameMetadataOak streaming at 30 FPS with sequence numbers", "[camera][scenario]")
{
    for (int i = 0; i < 5; ++i)
    {
        core::FrameMetadataOakT metadata;
        metadata.stream = core::StreamType_Color;
        metadata.sequence_number = static_cast<uint64_t>(i);

        CHECK(metadata.sequence_number == static_cast<uint64_t>(i));
    }
}

// =============================================================================
// Edge Cases
// =============================================================================
TEST_CASE("FrameMetadataOak with large sequence number", "[camera][edge]")
{
    core::FrameMetadataOakT metadata;
    metadata.sequence_number = UINT64_MAX;

    CHECK(metadata.sequence_number == UINT64_MAX);
}

TEST_CASE("FrameMetadataOak can update sequence number", "[camera][native]")
{
    core::FrameMetadataOakT metadata;
    metadata.sequence_number = 0;

    // Simulate frame counter increment.
    for (int i = 1; i <= 10; ++i)
    {
        metadata.sequence_number = static_cast<uint64_t>(i);
        CHECK(metadata.sequence_number == static_cast<uint64_t>(i));
    }
}

// =============================================================================
// FrameMetadataOakRecord Tests (timestamp lives on the Record wrapper)
// =============================================================================
TEST_CASE("FrameMetadataOakRecord serialization with DeviceDataTimestamp", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    auto record = std::make_shared<core::FrameMetadataOakRecordT>();
    record->data = std::make_shared<core::FrameMetadataOakT>();
    record->data->stream = core::StreamType_MonoLeft;
    record->data->sequence_number = 42;
    record->timestamp = std::make_shared<core::DeviceDataTimestamp>(1000000000LL, 2000000000LL, 3000000000LL);

    auto offset = core::FrameMetadataOakRecord::Pack(builder, record.get());
    builder.Finish(offset);

    auto deserialized = flatbuffers::GetRoot<core::FrameMetadataOakRecord>(builder.GetBufferPointer());

    CHECK(deserialized->timestamp()->available_time_local_common_clock() == 1000000000LL);
    CHECK(deserialized->timestamp()->sample_time_local_common_clock() == 2000000000LL);
    CHECK(deserialized->timestamp()->sample_time_raw_device_clock() == 3000000000LL);
    CHECK(deserialized->data()->stream() == core::StreamType_MonoLeft);
    CHECK(deserialized->data()->sequence_number() == 42);
}

TEST_CASE("FrameMetadataOakRecord can be unpacked with DeviceDataTimestamp", "[camera][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    auto original = std::make_shared<core::FrameMetadataOakRecordT>();
    original->data = std::make_shared<core::FrameMetadataOakT>();
    original->data->stream = core::StreamType_Color;
    original->data->sequence_number = 7;
    original->timestamp = std::make_shared<core::DeviceDataTimestamp>(111LL, 222LL, 333LL);

    auto offset = core::FrameMetadataOakRecord::Pack(builder, original.get());
    builder.Finish(offset);

    auto fb = flatbuffers::GetRoot<core::FrameMetadataOakRecord>(builder.GetBufferPointer());
    auto unpacked = std::make_shared<core::FrameMetadataOakRecordT>();
    fb->UnPackTo(unpacked.get());

    CHECK(unpacked->timestamp->available_time_local_common_clock() == 111LL);
    CHECK(unpacked->timestamp->sample_time_local_common_clock() == 222LL);
    CHECK(unpacked->timestamp->sample_time_raw_device_clock() == 333LL);
    CHECK(unpacked->data->stream == core::StreamType_Color);
    CHECK(unpacked->data->sequence_number == 7);
}
