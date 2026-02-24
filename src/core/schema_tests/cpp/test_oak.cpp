// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated FrameMetadata FlatBuffer struct.

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/oak_generated.h>

#include <type_traits>

#define VT(field) (field + 2) * 2
// Only keep Record VT asserts
static_assert(core::FrameMetadataRecord::VT_DATA == VT(0));
static_assert(std::is_trivially_copyable_v<core::FrameMetadata>);

// =============================================================================
// FrameMetadata Tests
// =============================================================================
TEST_CASE("FrameMetadata default construction", "[camera][native]")
{
    core::FrameMetadata metadata;

    // Integer field should be zero by default.
    CHECK(metadata.sequence_number() == 0);
    // Struct fields are always present (no null checks needed)
}

TEST_CASE("FrameMetadata can store timestamp", "[camera][native]")
{
    core::FrameMetadata metadata;

    // Create timestamp.
    core::Timestamp timestamp(1000000000, 2000000000);
    metadata.mutable_timestamp() = timestamp;

    CHECK(metadata.timestamp().device_time() == 1000000000);
    CHECK(metadata.timestamp().common_time() == 2000000000);
}

TEST_CASE("FrameMetadata can store sequence number", "[camera][native]")
{
    core::FrameMetadata metadata;

    metadata.mutate_sequence_number(42);

    CHECK(metadata.sequence_number() == 42);
}

TEST_CASE("FrameMetadata can store full metadata", "[camera][native]")
{
    core::FrameMetadata metadata;

    // Set all fields.
    core::Timestamp timestamp(3000000000, 4000000000);
    metadata.mutable_timestamp() = timestamp;
    metadata.mutate_sequence_number(100);

    CHECK(metadata.timestamp().device_time() == 3000000000);
    CHECK(metadata.timestamp().common_time() == 4000000000);
    CHECK(metadata.sequence_number() == 100);
}

// =============================================================================
// Realistic Camera Frame Scenarios
// =============================================================================
TEST_CASE("FrameMetadata first frame", "[camera][scenario]")
{
    core::FrameMetadata metadata;
    core::Timestamp timestamp(0, 1000000);
    metadata.mutable_timestamp() = timestamp;
    metadata.mutate_sequence_number(0);

    CHECK(metadata.sequence_number() == 0);
    CHECK(metadata.timestamp().device_time() == 0);
}

TEST_CASE("FrameMetadata streaming frames at 30 FPS", "[camera][scenario]")
{
    // Simulate 5 frames at 30 FPS (33.33ms interval = 33333333 ns).
    constexpr int64_t base_time = 1000000000;
    constexpr int64_t frame_interval = 33333333;

    for (int i = 0; i < 5; ++i)
    {
        core::FrameMetadata metadata;
        core::Timestamp timestamp(base_time + i * frame_interval,
                                  base_time + i * frame_interval + 100); // Small offset for common_time.
        metadata.mutable_timestamp() = timestamp;
        metadata.mutate_sequence_number(i);

        CHECK(metadata.sequence_number() == i);
        CHECK(metadata.timestamp().device_time() == base_time + i * frame_interval);
    }
}

TEST_CASE("FrameMetadata high frequency capture at 120 FPS", "[camera][scenario]")
{
    // 120 FPS = 8.33ms interval = 8333333 ns.
    core::FrameMetadata metadata;
    core::Timestamp timestamp(8333333, 8333400);
    metadata.mutable_timestamp() = timestamp;
    metadata.mutate_sequence_number(1);

    CHECK(metadata.sequence_number() == 1);
    CHECK(metadata.timestamp().device_time() == 8333333);
}

TEST_CASE("FrameMetadata sequence rollover scenario", "[camera][scenario]")
{
    // Test near max int32 boundary.
    core::FrameMetadata metadata;
    core::Timestamp timestamp(999999999999, 999999999999);
    metadata.mutable_timestamp() = timestamp;
    metadata.mutate_sequence_number(2147483646); // Near max int32.

    CHECK(metadata.sequence_number() == 2147483646);

    // Increment to max.
    metadata.mutate_sequence_number(2147483647);
    CHECK(metadata.sequence_number() == 2147483647);
}

// =============================================================================
// Edge Cases
// =============================================================================
TEST_CASE("FrameMetadata with negative sequence number", "[camera][edge]")
{
    // Although sequence numbers are typically positive, test negative values.
    core::FrameMetadata metadata;
    metadata.mutate_sequence_number(-1);

    CHECK(metadata.sequence_number() == -1);
}

TEST_CASE("FrameMetadata with zero timestamp", "[camera][edge]")
{
    core::FrameMetadata metadata;
    core::Timestamp timestamp(0, 0);
    metadata.mutable_timestamp() = timestamp;
    metadata.mutate_sequence_number(0);

    CHECK(metadata.timestamp().device_time() == 0);
    CHECK(metadata.timestamp().common_time() == 0);
}

TEST_CASE("FrameMetadata with negative timestamp", "[camera][edge]")
{
    // Test with negative timestamp values (valid for relative times).
    core::FrameMetadata metadata;
    core::Timestamp timestamp(-1000, -2000);
    metadata.mutable_timestamp() = timestamp;

    CHECK(metadata.timestamp().device_time() == -1000);
    CHECK(metadata.timestamp().common_time() == -2000);
}

TEST_CASE("FrameMetadata with large timestamp values", "[camera][edge]")
{
    core::FrameMetadata metadata;
    int64_t max_int64 = 9223372036854775807;
    core::Timestamp timestamp(max_int64, max_int64 - 1000);
    metadata.mutable_timestamp() = timestamp;
    metadata.mutate_sequence_number(1);

    CHECK(metadata.timestamp().device_time() == max_int64);
    CHECK(metadata.timestamp().common_time() == max_int64 - 1000);
}

TEST_CASE("FrameMetadata with max int32 sequence number", "[camera][edge]")
{
    core::FrameMetadata metadata;
    metadata.mutate_sequence_number(2147483647); // Max int32.

    CHECK(metadata.sequence_number() == 2147483647);
}

TEST_CASE("FrameMetadata with min int32 sequence number", "[camera][edge]")
{
    core::FrameMetadata metadata;
    metadata.mutate_sequence_number(-2147483648); // Min int32.

    CHECK(metadata.sequence_number() == -2147483648);
}

TEST_CASE("FrameMetadata can update sequence number", "[camera][native]")
{
    core::FrameMetadata metadata;
    metadata.mutate_sequence_number(0);

    // Simulate frame counter increment.
    for (int i = 1; i <= 10; ++i)
    {
        metadata.mutate_sequence_number(i);
        CHECK(metadata.sequence_number() == i);
    }
}

TEST_CASE("FrameMetadata can update timestamp", "[camera][native]")
{
    core::FrameMetadata metadata;

    // Set initial timestamp.
    core::Timestamp timestamp1(100, 200);
    metadata.mutable_timestamp() = timestamp1;
    CHECK(metadata.timestamp().device_time() == 100);

    // Update timestamp.
    core::Timestamp timestamp2(300, 400);
    metadata.mutable_timestamp() = timestamp2;
    CHECK(metadata.timestamp().device_time() == 300);
    CHECK(metadata.timestamp().common_time() == 400);
}
