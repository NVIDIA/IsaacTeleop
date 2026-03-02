// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated Pedals FlatBuffer types.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/pedals_generated.h>
#include <schema/timestamp_generated.h>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs for Generic3AxisPedalOutput table.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2

static_assert(core::Generic3AxisPedalOutput::VT_LEFT_PEDAL == VT(0));
static_assert(core::Generic3AxisPedalOutput::VT_RIGHT_PEDAL == VT(1));
static_assert(core::Generic3AxisPedalOutput::VT_RUDDER == VT(2));

static_assert(core::Generic3AxisPedalOutputRecord::VT_DATA == VT(0));
static_assert(core::Generic3AxisPedalOutputRecord::VT_TIMESTAMP == VT(1));

// =============================================================================
// Generic3AxisPedalOutputT Tests (table native type)
// =============================================================================
TEST_CASE("Generic3AxisPedalOutputT default construction", "[pedals][native]")
{
    core::Generic3AxisPedalOutputT output;

    // Float fields should be zero by default.
    CHECK(output.left_pedal == 0.0f);
    CHECK(output.right_pedal == 0.0f);
    CHECK(output.rudder == 0.0f);
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

    output.left_pedal = 1.0f;
    output.right_pedal = 0.0f;
    output.rudder = -0.5f;

    CHECK(output.left_pedal == Catch::Approx(1.0f));
    CHECK(output.right_pedal == Catch::Approx(0.0f));
    CHECK(output.rudder == Catch::Approx(-0.5f));
}

// =============================================================================
// Generic3AxisPedalOutputTrackedT Tests
// =============================================================================
TEST_CASE("Generic3AxisPedalOutputTrackedT default construction has null data", "[pedals][tracked]")
{
    core::Generic3AxisPedalOutputTrackedT tracked;

    CHECK(tracked.data == nullptr);
}

TEST_CASE("Generic3AxisPedalOutputTrackedT with data assigned", "[pedals][tracked]")
{
    core::Generic3AxisPedalOutputTrackedT tracked;
    tracked.data = std::make_shared<core::Generic3AxisPedalOutputT>();
    tracked.data->left_pedal = 0.5f;
    tracked.data->right_pedal = 0.3f;
    tracked.data->rudder = -0.2f;

    CHECK(tracked.data->left_pedal == Catch::Approx(0.5f));
    CHECK(tracked.data->right_pedal == Catch::Approx(0.3f));
    CHECK(tracked.data->rudder == Catch::Approx(-0.2f));
}

TEST_CASE("Generic3AxisPedalOutputTrackedT data can be reset to null", "[pedals][tracked]")
{
    core::Generic3AxisPedalOutputTrackedT tracked;
    tracked.data = std::make_shared<core::Generic3AxisPedalOutputT>();
    tracked.data->left_pedal = 0.8f;

    tracked.data.reset();

    CHECK(tracked.data == nullptr);
}

TEST_CASE("Generic3AxisPedalOutputRecord serialization with tracked data", "[pedals][tracked][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create native object with data.
    core::Generic3AxisPedalOutputT output;
    output.left_pedal = 0.5f;
    output.right_pedal = 0.5f;
    output.rudder = 0.0f;

    // Pack data before starting the RecordBuilder to avoid nested table building.
    auto data_offset = core::Generic3AxisPedalOutput::Pack(builder, &output);
    core::Generic3AxisPedalOutputRecordBuilder record_builder(builder);
    record_builder.add_data(data_offset);
    builder.Finish(record_builder.Finish());

    // Deserialize.
    auto* record = flatbuffers::GetRoot<core::Generic3AxisPedalOutputRecord>(builder.GetBufferPointer());
    CHECK(record->data()->left_pedal() == Catch::Approx(0.5f));
    CHECK(record->data()->right_pedal() == Catch::Approx(0.5f));
    CHECK(record->data()->rudder() == Catch::Approx(0.0f));
}

TEST_CASE("Generic3AxisPedalOutputRecord serialization without data", "[pedals][tracked][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Serialize a record with no data (inactive pedal).
    core::Generic3AxisPedalOutputRecordBuilder record_builder(builder);
    builder.Finish(record_builder.Finish());

    // Deserialize.
    auto* record = flatbuffers::GetRoot<core::Generic3AxisPedalOutputRecord>(builder.GetBufferPointer());
    CHECK(record->data() == nullptr);
}

// =============================================================================
// Generic3AxisPedalOutput Serialization Tests
// =============================================================================
TEST_CASE("Generic3AxisPedalOutput serialization and deserialization", "[pedals][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create native object.
    core::Generic3AxisPedalOutputT output;
    output.left_pedal = 0.8f;
    output.right_pedal = 0.2f;
    output.rudder = 0.33f;

    // Serialize.
    auto offset = core::Generic3AxisPedalOutput::Pack(builder, &output);
    builder.Finish(offset);

    // Deserialize.
    auto* deserialized = flatbuffers::GetRoot<core::Generic3AxisPedalOutput>(builder.GetBufferPointer());

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
    CHECK(unpacked->left_pedal == Catch::Approx(0.5f));
}


// =============================================================================
// Realistic Foot Pedal Scenarios
// =============================================================================
TEST_CASE("Generic3AxisPedalOutput full forward press", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutputT output;
    output.left_pedal = 1.0f;
    output.right_pedal = 1.0f;
    output.rudder = 0.0f;

    CHECK(output.left_pedal == Catch::Approx(1.0f));
    CHECK(output.right_pedal == Catch::Approx(1.0f));
    CHECK(output.rudder == Catch::Approx(0.0f));
}

TEST_CASE("Generic3AxisPedalOutput left turn with rudder", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutputT output;
    output.left_pedal = 0.5f;
    output.right_pedal = 0.5f;
    output.rudder = -1.0f; // Full left rudder.

    CHECK(output.rudder == Catch::Approx(-1.0f));
}

TEST_CASE("Generic3AxisPedalOutput right turn with rudder", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutputT output;
    output.left_pedal = 0.5f;
    output.right_pedal = 0.5f;
    output.rudder = 1.0f; // Full right rudder.

    CHECK(output.rudder == Catch::Approx(1.0f));
}

TEST_CASE("Generic3AxisPedalOutput differential braking", "[pedals][scenario]")
{
    // Simulating differential braking (left brake only).
    core::Generic3AxisPedalOutputT output;
    output.left_pedal = 0.0f; // Left brake applied.
    output.right_pedal = 0.8f; // Right pedal pressed.
    output.rudder = 0.0f;

    CHECK(output.left_pedal == Catch::Approx(0.0f));
    CHECK(output.right_pedal == Catch::Approx(0.8f));
}

TEST_CASE("Generic3AxisPedalOutput neutral position", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutputT output;
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
    output.left_pedal = 0.0f;
    output.right_pedal = 0.0f;
    output.rudder = 0.0f;

    auto offset = core::Generic3AxisPedalOutput::Pack(builder, &output);
    builder.Finish(offset);

    // Buffer should be reasonably small (under 100 bytes for this simple message).
    CHECK(builder.GetSize() < 100);
}

// =============================================================================
// Generic3AxisPedalOutputRecord Tests (timestamp lives on the Record wrapper)
// =============================================================================
TEST_CASE("Generic3AxisPedalOutputRecord serialization with DeviceDataTimestamp", "[pedals][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    auto record = std::make_shared<core::Generic3AxisPedalOutputRecordT>();
    record->data = std::make_shared<core::Generic3AxisPedalOutputT>();
    record->data->left_pedal = 0.8f;
    record->data->right_pedal = 0.2f;
    record->data->rudder = 0.5f;
    record->timestamp = std::make_shared<core::DeviceDataTimestamp>(1000000000LL, 2000000000LL, 3000000000LL);

    auto offset = core::Generic3AxisPedalOutputRecord::Pack(builder, record.get());
    builder.Finish(offset);

    auto deserialized = flatbuffers::GetRoot<core::Generic3AxisPedalOutputRecord>(builder.GetBufferPointer());

    CHECK(deserialized->timestamp()->available_time_local_common_clock() == 1000000000LL);
    CHECK(deserialized->timestamp()->sample_time_local_common_clock() == 2000000000LL);
    CHECK(deserialized->timestamp()->sample_time_raw_device_clock() == 3000000000LL);
    CHECK(deserialized->data()->left_pedal() == Catch::Approx(0.8f));
    CHECK(deserialized->data()->right_pedal() == Catch::Approx(0.2f));
    CHECK(deserialized->data()->rudder() == Catch::Approx(0.5f));
}

TEST_CASE("Generic3AxisPedalOutputRecord can be unpacked with DeviceDataTimestamp", "[pedals][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    auto original = std::make_shared<core::Generic3AxisPedalOutputRecordT>();
    original->data = std::make_shared<core::Generic3AxisPedalOutputT>();
    original->data->left_pedal = 0.5f;
    original->timestamp = std::make_shared<core::DeviceDataTimestamp>(111LL, 222LL, 333LL);

    auto offset = core::Generic3AxisPedalOutputRecord::Pack(builder, original.get());
    builder.Finish(offset);

    auto fb = flatbuffers::GetRoot<core::Generic3AxisPedalOutputRecord>(builder.GetBufferPointer());
    auto unpacked = std::make_shared<core::Generic3AxisPedalOutputRecordT>();
    fb->UnPackTo(unpacked.get());

    CHECK(unpacked->timestamp->available_time_local_common_clock() == 111LL);
    CHECK(unpacked->timestamp->sample_time_local_common_clock() == 222LL);
    CHECK(unpacked->timestamp->sample_time_raw_device_clock() == 333LL);
    CHECK(unpacked->data->left_pedal == Catch::Approx(0.5f));
}
