// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated Pedals FlatBuffer types.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/pedals_generated.h>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs for Generic3AxisPedalOutput table.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2

static_assert(core::Generic3AxisPedalOutput::VT_IS_ACTIVE == VT(0));
static_assert(core::Generic3AxisPedalOutput::VT_TIMESTAMP == VT(1));
static_assert(core::Generic3AxisPedalOutput::VT_LEFT_PEDAL == VT(2));
static_assert(core::Generic3AxisPedalOutput::VT_RIGHT_PEDAL == VT(3));
static_assert(core::Generic3AxisPedalOutput::VT_RUDDER == VT(4));

static_assert(core::Generic3AxisPedalOutputRecord::VT_DATA == VT(0));

// =============================================================================
// Generic3AxisPedalOutputT Tests (table native type)
// =============================================================================
TEST_CASE("Generic3AxisPedalOutputT default construction", "[pedals][native]")
{
    core::Generic3AxisPedalOutputT output;

    // is_active should be false by default.
    CHECK(output.is_active == false);
    // Timestamp pointer should be null by default.
    CHECK(output.timestamp == nullptr);
    // Float fields should be zero by default.
    CHECK(output.left_pedal == 0.0f);
    CHECK(output.right_pedal == 0.0f);
    CHECK(output.rudder == 0.0f);
}

TEST_CASE("Generic3AxisPedalOutputT can handle is_active value properly", "[pedals][native]")
{
    core::Generic3AxisPedalOutputT output;

    // Default is_active should be false.
    CHECK(output.is_active == false);

    // Set is_active to true.
    output.is_active = true;
    CHECK(output.is_active == true);
}

TEST_CASE("Generic3AxisPedalOutputT can store timestamp", "[pedals][native]")
{
    core::Generic3AxisPedalOutputT output;

    // Create timestamp.
    output.timestamp = std::make_unique<core::Timestamp>(1000000000, 2000000000);

    CHECK(output.timestamp != nullptr);
    CHECK(output.timestamp->device_time() == 1000000000);
    CHECK(output.timestamp->common_time() == 2000000000);
}

TEST_CASE("Generic3AxisPedalOutputT can store pedal values", "[pedals][native]")
{
    core::Generic3AxisPedalOutputT output;

    output.left_pedal = 0.75f;
    output.right_pedal = 0.25f;
    output.rudder = 0.5f;

    CHECK(output.left_pedal == Catch::Approx(0.75f));
    CHECK(output.right_pedal == Catch::Approx(0.25f));
    CHECK(output.rudder == Catch::Approx(0.5f));
}

TEST_CASE("Generic3AxisPedalOutputT can store full output", "[pedals][native]")
{
    core::Generic3AxisPedalOutputT output;

    // Set all fields.
    output.is_active = true;
    output.timestamp = std::make_unique<core::Timestamp>(3000000000, 4000000000);
    output.left_pedal = 1.0f;
    output.right_pedal = 0.0f;
    output.rudder = -0.5f;

    CHECK(output.is_active == true);
    CHECK(output.timestamp != nullptr);
    CHECK(output.timestamp->device_time() == 3000000000);
    CHECK(output.left_pedal == Catch::Approx(1.0f));
    CHECK(output.right_pedal == Catch::Approx(0.0f));
    CHECK(output.rudder == Catch::Approx(-0.5f));
}

// =============================================================================
// Generic3AxisPedalOutput Serialization Tests
// =============================================================================
TEST_CASE("Generic3AxisPedalOutput serialization and deserialization", "[pedals][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create native object.
    core::Generic3AxisPedalOutputT output;
    output.is_active = true;
    output.timestamp = std::make_unique<core::Timestamp>(1234567890, 9876543210);
    output.left_pedal = 0.8f;
    output.right_pedal = 0.2f;
    output.rudder = 0.33f;

    // Serialize.
    auto offset = core::Generic3AxisPedalOutput::Pack(builder, &output);
    builder.Finish(offset);

    // Deserialize.
    auto* deserialized = flatbuffers::GetRoot<core::Generic3AxisPedalOutput>(builder.GetBufferPointer());

    // Verify is_active.
    CHECK(deserialized->is_active() == true);

    // Verify timestamp.
    REQUIRE(deserialized->timestamp() != nullptr);
    CHECK(deserialized->timestamp()->device_time() == 1234567890);
    CHECK(deserialized->timestamp()->common_time() == 9876543210);

    // Verify pedal values.
    CHECK(deserialized->left_pedal() == Catch::Approx(0.8f));
    CHECK(deserialized->right_pedal() == Catch::Approx(0.2f));
    CHECK(deserialized->rudder() == Catch::Approx(0.33f));
}

TEST_CASE("Generic3AxisPedalOutput can be unpacked from buffer", "[pedals][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create native object with minimal data.
    core::Generic3AxisPedalOutputT output;
    output.is_active = true;
    output.timestamp = std::make_unique<core::Timestamp>(100, 200);
    output.left_pedal = 0.5f;

    // Serialize.
    auto offset = core::Generic3AxisPedalOutput::Pack(builder, &output);
    builder.Finish(offset);

    // Deserialize to table.
    auto* table = flatbuffers::GetRoot<core::Generic3AxisPedalOutput>(builder.GetBufferPointer());

    // Unpack to native.
    auto unpacked = std::make_unique<core::Generic3AxisPedalOutputT>();
    table->UnPackTo(unpacked.get());

    // Verify.
    CHECK(unpacked->is_active == true);
    REQUIRE(unpacked->timestamp != nullptr);
    CHECK(unpacked->timestamp->device_time() == 100);
    CHECK(unpacked->timestamp->common_time() == 200);
    CHECK(unpacked->left_pedal == Catch::Approx(0.5f));
}

TEST_CASE("Generic3AxisPedalOutput without timestamp", "[pedals][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::Generic3AxisPedalOutputT output;
    // timestamp is intentionally left null.
    output.is_active = true;
    output.left_pedal = 0.6f;
    output.right_pedal = 0.4f;
    output.rudder = 0.0f;

    auto offset = core::Generic3AxisPedalOutput::Pack(builder, &output);
    builder.Finish(offset);

    auto* deserialized = flatbuffers::GetRoot<core::Generic3AxisPedalOutput>(builder.GetBufferPointer());

    CHECK(deserialized->is_active() == true);
    CHECK(deserialized->timestamp() == nullptr);
    CHECK(deserialized->left_pedal() == Catch::Approx(0.6f));
    CHECK(deserialized->right_pedal() == Catch::Approx(0.4f));
    CHECK(deserialized->rudder() == Catch::Approx(0.0f));
}

// =============================================================================
// Realistic Foot Pedal Scenarios
// =============================================================================
TEST_CASE("Generic3AxisPedalOutput full forward press", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutputT output;
    output.is_active = true;
    output.timestamp = std::make_unique<core::Timestamp>(1000000, 1000000);
    output.left_pedal = 1.0f;
    output.right_pedal = 1.0f;
    output.rudder = 0.0f;

    CHECK(output.is_active == true);
    CHECK(output.left_pedal == Catch::Approx(1.0f));
    CHECK(output.right_pedal == Catch::Approx(1.0f));
    CHECK(output.rudder == Catch::Approx(0.0f));
}

TEST_CASE("Generic3AxisPedalOutput left turn with rudder", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutputT output;
    output.is_active = true;
    output.timestamp = std::make_unique<core::Timestamp>(2000000, 2000000);
    output.left_pedal = 0.5f;
    output.right_pedal = 0.5f;
    output.rudder = -1.0f; // Full left rudder.

    CHECK(output.rudder == Catch::Approx(-1.0f));
}

TEST_CASE("Generic3AxisPedalOutput right turn with rudder", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutputT output;
    output.is_active = true;
    output.timestamp = std::make_unique<core::Timestamp>(3000000, 3000000);
    output.left_pedal = 0.5f;
    output.right_pedal = 0.5f;
    output.rudder = 1.0f; // Full right rudder.

    CHECK(output.rudder == Catch::Approx(1.0f));
}

TEST_CASE("Generic3AxisPedalOutput differential braking", "[pedals][scenario]")
{
    // Simulating differential braking (left brake only).
    core::Generic3AxisPedalOutputT output;
    output.is_active = true;
    output.timestamp = std::make_unique<core::Timestamp>(4000000, 4000000);
    output.left_pedal = 0.0f; // Left brake applied.
    output.right_pedal = 0.8f; // Right pedal pressed.
    output.rudder = 0.0f;

    CHECK(output.left_pedal == Catch::Approx(0.0f));
    CHECK(output.right_pedal == Catch::Approx(0.8f));
}

TEST_CASE("Generic3AxisPedalOutput neutral position", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutputT output;
    output.is_active = true;
    output.timestamp = std::make_unique<core::Timestamp>(5000000, 5000000);
    output.left_pedal = 0.0f;
    output.right_pedal = 0.0f;
    output.rudder = 0.0f;

    CHECK(output.left_pedal == Catch::Approx(0.0f));
    CHECK(output.right_pedal == Catch::Approx(0.0f));
    CHECK(output.rudder == Catch::Approx(0.0f));
}

// =============================================================================
// Edge Cases
// =============================================================================
TEST_CASE("Generic3AxisPedalOutput with negative values", "[pedals][edge]")
{
    // Although pedal values are typically 0-1, test negative values.
    core::Generic3AxisPedalOutputT output;
    output.left_pedal = -0.5f;
    output.right_pedal = -0.25f;
    output.rudder = -1.0f;

    CHECK(output.left_pedal == Catch::Approx(-0.5f));
    CHECK(output.right_pedal == Catch::Approx(-0.25f));
    CHECK(output.rudder == Catch::Approx(-1.0f));
}

TEST_CASE("Generic3AxisPedalOutput with values greater than 1", "[pedals][edge]")
{
    // Test values exceeding typical range.
    core::Generic3AxisPedalOutputT output;
    output.left_pedal = 1.5f;
    output.right_pedal = 2.0f;
    output.rudder = 1.5f;

    CHECK(output.left_pedal == Catch::Approx(1.5f));
    CHECK(output.right_pedal == Catch::Approx(2.0f));
    CHECK(output.rudder == Catch::Approx(1.5f));
}

TEST_CASE("Generic3AxisPedalOutput with large timestamp values", "[pedals][edge]")
{
    core::Generic3AxisPedalOutputT output;
    output.is_active = true;
    int64_t max_int64 = 9223372036854775807;
    output.timestamp = std::make_unique<core::Timestamp>(max_int64, max_int64 - 1000);
    output.left_pedal = 0.5f;

    CHECK(output.timestamp->device_time() == max_int64);
    CHECK(output.timestamp->common_time() == max_int64 - 1000);
}

TEST_CASE("Generic3AxisPedalOutput buffer size is reasonable", "[pedals][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::Generic3AxisPedalOutputT output;
    output.is_active = true;
    output.timestamp = std::make_unique<core::Timestamp>(0, 0);
    output.left_pedal = 0.0f;
    output.right_pedal = 0.0f;
    output.rudder = 0.0f;

    auto offset = core::Generic3AxisPedalOutput::Pack(builder, &output);
    builder.Finish(offset);

    // Buffer should be reasonably small (under 100 bytes for this simple message).
    CHECK(builder.GetSize() < 100);
}

TEST_CASE("Generic3AxisPedalOutput with is_active false", "[pedals][edge]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::Generic3AxisPedalOutputT output;
    output.is_active = false;
    output.timestamp = std::make_unique<core::Timestamp>(1000, 2000);
    output.left_pedal = 0.5f;
    output.right_pedal = 0.5f;
    output.rudder = 0.0f;

    auto offset = core::Generic3AxisPedalOutput::Pack(builder, &output);
    builder.Finish(offset);

    auto* deserialized = flatbuffers::GetRoot<core::Generic3AxisPedalOutput>(builder.GetBufferPointer());

    // Verify is_active is false but other data is still present.
    CHECK(deserialized->is_active() == false);
    REQUIRE(deserialized->timestamp() != nullptr);
    CHECK(deserialized->left_pedal() == Catch::Approx(0.5f));
    CHECK(deserialized->right_pedal() == Catch::Approx(0.5f));
    CHECK(deserialized->rudder() == Catch::Approx(0.0f));
}
