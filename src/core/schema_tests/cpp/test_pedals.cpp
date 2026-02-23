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

static_assert(core::Generic3AxisPedalOutput::VT_IS_VALID == VT(0));
static_assert(core::Generic3AxisPedalOutput::VT_LEFT_PEDAL == VT(1));
static_assert(core::Generic3AxisPedalOutput::VT_RIGHT_PEDAL == VT(2));
static_assert(core::Generic3AxisPedalOutput::VT_RUDDER == VT(3));

// =============================================================================
// Generic3AxisPedalOutputT Tests (table native type)
// =============================================================================
TEST_CASE("Generic3AxisPedalOutputT default construction", "[pedals][native]")
{
    core::Generic3AxisPedalOutputT output;

    // is_valid should be false by default.
    CHECK(output.is_valid == false);
    // Float fields should be zero by default.
    CHECK(output.left_pedal == 0.0f);
    CHECK(output.right_pedal == 0.0f);
    CHECK(output.rudder == 0.0f);
}

TEST_CASE("Generic3AxisPedalOutputT can handle is_valid value properly", "[pedals][native]")
{
    core::Generic3AxisPedalOutputT output;

    // Default is_valid should be false.
    CHECK(output.is_valid == false);

    // Set is_valid to true.
    output.is_valid = true;
    CHECK(output.is_valid == true);
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
    output.is_valid = true;
    output.left_pedal = 1.0f;
    output.right_pedal = 0.0f;
    output.rudder = -0.5f;

    CHECK(output.is_valid == true);
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
    output.is_valid = true;
    output.left_pedal = 0.8f;
    output.right_pedal = 0.2f;
    output.rudder = 0.33f;

    // Create Generic3AxisPedalOutputRecord for serialization (root type)
    core::Generic3AxisPedalOutputRecordT record;
    record.data = std::make_unique<core::Generic3AxisPedalOutputT>(output);
    record.timestamp = std::make_unique<core::DeviceDataTimestamp>(1234567890, 9876543210, 0);

    // Serialize.
    auto offset = core::Generic3AxisPedalOutputRecord::Pack(builder, &record);
    builder.Finish(offset);

    // Deserialize.
    auto* deserialized_record = flatbuffers::GetRoot<core::Generic3AxisPedalOutputRecord>(builder.GetBufferPointer());
    REQUIRE(deserialized_record->data() != nullptr);
    auto* deserialized = deserialized_record->data();

    // Verify is_valid.
    CHECK(deserialized->is_valid() == true);

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
    output.is_valid = true;
    output.left_pedal = 0.5f;

    core::Generic3AxisPedalOutputRecordT record;
    record.data = std::make_unique<core::Generic3AxisPedalOutputT>(output);
    record.timestamp = std::make_unique<core::DeviceDataTimestamp>(100, 200, 0);

    // Serialize.
    auto offset = core::Generic3AxisPedalOutputRecord::Pack(builder, &record);
    builder.Finish(offset);

    // Deserialize to table.
    auto* record_table = flatbuffers::GetRoot<core::Generic3AxisPedalOutputRecord>(builder.GetBufferPointer());
    REQUIRE(record_table->data() != nullptr);

    // Unpack data to native.
    auto unpacked = std::make_unique<core::Generic3AxisPedalOutputT>();
    record_table->data()->UnPackTo(unpacked.get());

    // Verify.
    CHECK(unpacked->is_valid == true);
    CHECK(unpacked->left_pedal == Catch::Approx(0.5f));
}

TEST_CASE("Generic3AxisPedalOutputRecord with null timestamp", "[pedals][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::Generic3AxisPedalOutputT output;
    output.is_valid = true;
    output.left_pedal = 0.6f;
    output.right_pedal = 0.4f;
    output.rudder = 0.0f;

    core::Generic3AxisPedalOutputRecordT record;
    record.data = std::make_unique<core::Generic3AxisPedalOutputT>(output);
    // timestamp is intentionally left null.

    auto offset = core::Generic3AxisPedalOutputRecord::Pack(builder, &record);
    builder.Finish(offset);

    auto* deserialized_record = flatbuffers::GetRoot<core::Generic3AxisPedalOutputRecord>(builder.GetBufferPointer());
    REQUIRE(deserialized_record->data() != nullptr);
    auto* deserialized = deserialized_record->data();

    CHECK(deserialized->is_valid() == true);
    CHECK(deserialized_record->timestamp() == nullptr);
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
    output.is_valid = true;
    output.left_pedal = 1.0f;
    output.right_pedal = 1.0f;
    output.rudder = 0.0f;

    CHECK(output.is_valid == true);
    CHECK(output.left_pedal == Catch::Approx(1.0f));
    CHECK(output.right_pedal == Catch::Approx(1.0f));
    CHECK(output.rudder == Catch::Approx(0.0f));
}

TEST_CASE("Generic3AxisPedalOutput left turn with rudder", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutputT output;
    output.is_valid = true;
    output.left_pedal = 0.5f;
    output.right_pedal = 0.5f;
    output.rudder = -1.0f; // Full left rudder.

    CHECK(output.rudder == Catch::Approx(-1.0f));
}

TEST_CASE("Generic3AxisPedalOutput right turn with rudder", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutputT output;
    output.is_valid = true;
    output.left_pedal = 0.5f;
    output.right_pedal = 0.5f;
    output.rudder = 1.0f; // Full right rudder.

    CHECK(output.rudder == Catch::Approx(1.0f));
}

TEST_CASE("Generic3AxisPedalOutput differential braking", "[pedals][scenario]")
{
    // Simulating differential braking (left brake only).
    core::Generic3AxisPedalOutputT output;
    output.is_valid = true;
    output.left_pedal = 0.0f; // Left brake applied.
    output.right_pedal = 0.8f; // Right pedal pressed.
    output.rudder = 0.0f;

    CHECK(output.left_pedal == Catch::Approx(0.0f));
    CHECK(output.right_pedal == Catch::Approx(0.8f));
}

TEST_CASE("Generic3AxisPedalOutput neutral position", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutputT output;
    output.is_valid = true;
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


TEST_CASE("Generic3AxisPedalOutput buffer size is reasonable", "[pedals][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::Generic3AxisPedalOutputT output;
    output.is_valid = true;
    output.left_pedal = 0.0f;
    output.right_pedal = 0.0f;
    output.rudder = 0.0f;

    core::Generic3AxisPedalOutputRecordT record;
    record.data = std::make_unique<core::Generic3AxisPedalOutputT>(output);
    record.timestamp = std::make_unique<core::DeviceDataTimestamp>(0, 0, 0);

    auto offset = core::Generic3AxisPedalOutputRecord::Pack(builder, &record);
    builder.Finish(offset);

    // Buffer should be reasonably small (under 100 bytes for this simple message).
    CHECK(builder.GetSize() < 100);
}

TEST_CASE("Generic3AxisPedalOutput with is_valid false", "[pedals][edge]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::Generic3AxisPedalOutputT output;
    output.is_valid = false;
    output.left_pedal = 0.5f;
    output.right_pedal = 0.5f;
    output.rudder = 0.0f;

    core::Generic3AxisPedalOutputRecordT record;
    record.data = std::make_unique<core::Generic3AxisPedalOutputT>(output);
    record.timestamp = std::make_unique<core::DeviceDataTimestamp>(1000, 2000, 0);

    auto offset = core::Generic3AxisPedalOutputRecord::Pack(builder, &record);
    builder.Finish(offset);

    auto* deserialized_record = flatbuffers::GetRoot<core::Generic3AxisPedalOutputRecord>(builder.GetBufferPointer());
    REQUIRE(deserialized_record->data() != nullptr);
    auto* deserialized = deserialized_record->data();

    // Verify is_valid is false but other data is still present.
    CHECK(deserialized->is_valid() == false);
    CHECK(deserialized->left_pedal() == Catch::Approx(0.5f));
    CHECK(deserialized->right_pedal() == Catch::Approx(0.5f));
    CHECK(deserialized->rudder() == Catch::Approx(0.0f));
}
