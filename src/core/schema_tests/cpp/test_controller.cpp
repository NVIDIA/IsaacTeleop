// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated Controller FlatBuffer messages.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/controller_generated.h>
#include <schema/timestamp_generated.h>

#include <type_traits>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs.
// These ensure schema field IDs remain stable across changes.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2

// ControllerSnapshot field IDs (table)
static_assert(core::ControllerSnapshot::VT_GRIP_POSE == VT(0));
static_assert(core::ControllerSnapshot::VT_AIM_POSE == VT(1));
static_assert(core::ControllerSnapshot::VT_INPUTS == VT(2));

// ControllerSnapshotRecord field IDs
static_assert(core::ControllerSnapshotRecord::VT_DATA == VT(0));
static_assert(core::ControllerSnapshotRecord::VT_TIMESTAMP == VT(1));

// =============================================================================
// Compile-time verification that helper types are structs (not tables)
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::ControllerInputState>);
static_assert(std::is_trivially_copyable_v<core::ControllerPose>);
static_assert(std::is_trivially_copyable_v<core::DeviceDataTimestamp>);

// =============================================================================
// ControllerInputState Tests (struct)
// =============================================================================
TEST_CASE("ControllerInputState default construction", "[controller][struct]")
{
    core::ControllerInputState inputs{};

    // Default values should be false/zero.
    CHECK(inputs.primary_click() == false);
    CHECK(inputs.secondary_click() == false);
    CHECK(inputs.thumbstick_click() == false);
    CHECK(inputs.thumbstick_x() == 0.0f);
    CHECK(inputs.thumbstick_y() == 0.0f);
    CHECK(inputs.squeeze_value() == 0.0f);
    CHECK(inputs.trigger_value() == 0.0f);
}

TEST_CASE("ControllerInputState can store button states", "[controller][struct]")
{
    core::ControllerInputState inputs(true, true, true, 0.0f, 0.0f, 0.0f, 0.0f);

    CHECK(inputs.primary_click() == true);
    CHECK(inputs.secondary_click() == true);
    CHECK(inputs.thumbstick_click() == true);
}

TEST_CASE("ControllerInputState can store analog values", "[controller][struct]")
{
    core::ControllerInputState inputs(false, false, false, 0.5f, -0.75f, 0.8f, 1.0f);

    CHECK(inputs.thumbstick_x() == Catch::Approx(0.5f));
    CHECK(inputs.thumbstick_y() == Catch::Approx(-0.75f));
    CHECK(inputs.squeeze_value() == Catch::Approx(0.8f));
    CHECK(inputs.trigger_value() == Catch::Approx(1.0f));
}

// =============================================================================
// ControllerPose Tests (struct)
// =============================================================================
TEST_CASE("ControllerPose default construction", "[controller][struct]")
{
    core::ControllerPose pose{};

    CHECK(pose.is_valid() == false);
}

TEST_CASE("ControllerPose can store pose data", "[controller][struct]")
{
    core::Point position(1.0f, 2.0f, 3.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose p(position, orientation);
    core::ControllerPose controller_pose(p, true);

    CHECK(controller_pose.is_valid() == true);
    CHECK(controller_pose.pose().position().x() == Catch::Approx(1.0f));
    CHECK(controller_pose.pose().position().y() == Catch::Approx(2.0f));
    CHECK(controller_pose.pose().position().z() == Catch::Approx(3.0f));
}

// =============================================================================
// DeviceDataTimestamp Tests (struct)
// =============================================================================
TEST_CASE("DeviceDataTimestamp default construction", "[controller][struct]")
{
    core::DeviceDataTimestamp timestamp{};

    CHECK(timestamp.available_time_local_common_clock() == 0);
    CHECK(timestamp.sample_time_local_common_clock() == 0);
    CHECK(timestamp.sample_time_raw_device_clock() == 0);
}

TEST_CASE("DeviceDataTimestamp can store timestamp values", "[controller][struct]")
{
    core::DeviceDataTimestamp timestamp(1000000000LL, 2000000000LL, 3000000000LL);

    CHECK(timestamp.available_time_local_common_clock() == 1000000000LL);
    CHECK(timestamp.sample_time_local_common_clock() == 2000000000LL);
    CHECK(timestamp.sample_time_raw_device_clock() == 3000000000LL);
}

// =============================================================================
// ControllerSnapshotT Tests (table native type)
// =============================================================================
TEST_CASE("ControllerSnapshotT can store complete controller state", "[controller][table]")
{
    // Create grip pose
    core::Point grip_pos(1.0f, 2.0f, 3.0f);
    core::Quaternion grip_orient(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose grip_p(grip_pos, grip_orient);
    core::ControllerPose grip_pose(grip_p, true);

    // Create aim pose
    core::Point aim_pos(4.0f, 5.0f, 6.0f);
    core::Quaternion aim_orient(0.0f, 0.707f, 0.0f, 0.707f);
    core::Pose aim_p(aim_pos, aim_orient);
    core::ControllerPose aim_pose(aim_p, true);

    // Create inputs
    core::ControllerInputState inputs(true, false, true, 0.5f, -0.5f, 0.8f, 1.0f);

    core::ControllerSnapshotT snapshot;
    snapshot.grip_pose = std::make_shared<core::ControllerPose>(grip_pose);
    snapshot.aim_pose = std::make_shared<core::ControllerPose>(aim_pose);
    snapshot.inputs = std::make_shared<core::ControllerInputState>(inputs);

    CHECK(snapshot.grip_pose->is_valid() == true);
    CHECK(snapshot.aim_pose->is_valid() == true);
    CHECK(snapshot.inputs->primary_click() == true);
    CHECK(snapshot.inputs->trigger_value() == Catch::Approx(1.0f));
}

// =============================================================================
// ControllerSnapshotRecordT Tests (table native type)
// =============================================================================
TEST_CASE("ControllerSnapshotRecordT default construction", "[controller][native]")
{
    core::ControllerSnapshotRecordT record;

    CHECK(record.data == nullptr);
}

// =============================================================================
// ControllerSnapshotRecord Serialization Tests
// =============================================================================
TEST_CASE("ControllerSnapshotRecord serialization and deserialization", "[controller][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create struct fields
    core::Point pos(1.0f, 2.0f, 3.0f);
    core::Quaternion orient(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose p(pos, orient);
    core::ControllerPose grip(p, true);
    core::ControllerInputState inputs(true, false, false, 0.5f, 0.0f, 0.5f, 0.5f);

    auto snapshot_offset = core::CreateControllerSnapshot(builder, &grip, &grip, &inputs);
    core::ControllerSnapshotRecordBuilder record_builder(builder);
    record_builder.add_data(snapshot_offset);
    builder.Finish(record_builder.Finish());

    // Deserialize
    auto* deserialized = flatbuffers::GetRoot<core::ControllerSnapshotRecord>(builder.GetBufferPointer());

    CHECK(deserialized->data()->inputs()->primary_click() == true);
}

TEST_CASE("ControllerSnapshotRecord can be unpacked from buffer", "[controller][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Build an empty ControllerSnapshot table
    auto snapshot_offset = core::CreateControllerSnapshot(builder);
    core::ControllerSnapshotRecordBuilder record_builder(builder);
    record_builder.add_data(snapshot_offset);
    builder.Finish(record_builder.Finish());

    // Deserialize to table
    auto* table = flatbuffers::GetRoot<core::ControllerSnapshotRecord>(builder.GetBufferPointer());

    // Unpack to native
    auto unpacked = std::make_unique<core::ControllerSnapshotRecordT>();
    table->UnPackTo(unpacked.get());

    CHECK(unpacked->data != nullptr);
}

// =============================================================================
// ControllerSnapshotRecord Tests (timestamp lives on the Record wrapper)
// =============================================================================
TEST_CASE("ControllerSnapshotRecord serialization with DeviceDataTimestamp", "[controller][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    auto record = std::make_shared<core::ControllerSnapshotRecordT>();
    record->data = std::make_shared<core::ControllerSnapshotT>();

    core::Point pos(1.0f, 2.0f, 3.0f);
    core::Quaternion orient(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose p(pos, orient);
    core::ControllerPose grip(p, true);
    core::ControllerInputState inputs(true, false, false, 0.5f, 0.0f, 0.5f, 0.5f);

    record->data->grip_pose = std::make_shared<core::ControllerPose>(grip);
    record->data->aim_pose = std::make_shared<core::ControllerPose>(grip);
    record->data->inputs = std::make_shared<core::ControllerInputState>(inputs);
    record->timestamp = std::make_shared<core::DeviceDataTimestamp>(1000000000LL, 2000000000LL, 3000000000LL);

    auto offset = core::ControllerSnapshotRecord::Pack(builder, record.get());
    builder.Finish(offset);

    auto deserialized = flatbuffers::GetRoot<core::ControllerSnapshotRecord>(builder.GetBufferPointer());

    CHECK(deserialized->timestamp()->available_time_local_common_clock() == 1000000000LL);
    CHECK(deserialized->timestamp()->sample_time_local_common_clock() == 2000000000LL);
    CHECK(deserialized->timestamp()->sample_time_raw_device_clock() == 3000000000LL);
    CHECK(deserialized->data()->inputs()->primary_click() == true);
    CHECK(deserialized->data()->grip_pose()->is_valid() == true);
}

TEST_CASE("ControllerSnapshotRecord can be unpacked with DeviceDataTimestamp", "[controller][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    auto original = std::make_shared<core::ControllerSnapshotRecordT>();
    original->data = std::make_shared<core::ControllerSnapshotT>();
    original->timestamp = std::make_shared<core::DeviceDataTimestamp>(111LL, 222LL, 333LL);

    auto offset = core::ControllerSnapshotRecord::Pack(builder, original.get());
    builder.Finish(offset);

    auto fb = flatbuffers::GetRoot<core::ControllerSnapshotRecord>(builder.GetBufferPointer());
    auto unpacked = std::make_shared<core::ControllerSnapshotRecordT>();
    fb->UnPackTo(unpacked.get());

    CHECK(unpacked->timestamp->available_time_local_common_clock() == 111LL);
    CHECK(unpacked->timestamp->sample_time_local_common_clock() == 222LL);
    CHECK(unpacked->timestamp->sample_time_raw_device_clock() == 333LL);
    CHECK(unpacked->data != nullptr);
}
