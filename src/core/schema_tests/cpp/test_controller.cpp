// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated Controller FlatBuffer messages.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/controller_generated.h>

#include <type_traits>

// =============================================================================
// Compile-time verification that controller types are structs (not tables)
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::ControllerInputState>);
static_assert(std::is_trivially_copyable_v<core::ControllerPose>);
static_assert(std::is_trivially_copyable_v<core::ControllerSnapshot>);
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

    CHECK(timestamp.sample_time_device_clock() == 0);
    CHECK(timestamp.sample_time_common_clock() == 0);
    CHECK(timestamp.available_time_common_clock() == 0);
}

TEST_CASE("DeviceDataTimestamp can store timestamp values", "[controller][struct]")
{
    core::DeviceDataTimestamp timestamp(1000000000, 2000000000, 3000000000);

    CHECK(timestamp.sample_time_device_clock() == 1000000000);
    CHECK(timestamp.sample_time_common_clock() == 2000000000);
    CHECK(timestamp.available_time_common_clock() == 3000000000);
}

// =============================================================================
// ControllerSnapshot Tests (struct)
// =============================================================================
TEST_CASE("ControllerSnapshot default construction", "[controller][struct]")
{
    core::ControllerSnapshot snapshot{};

    CHECK(snapshot.is_active() == false);
}

TEST_CASE("ControllerSnapshot can store complete controller state", "[controller][struct]")
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

    // Create snapshot
    core::ControllerSnapshot snapshot(grip_pose, aim_pose, inputs, true);

    CHECK(snapshot.is_active() == true);
    CHECK(snapshot.grip_pose().is_valid() == true);
    CHECK(snapshot.aim_pose().is_valid() == true);
    CHECK(snapshot.inputs().primary_click() == true);
    CHECK(snapshot.inputs().trigger_value() == Catch::Approx(1.0f));
}

// =============================================================================
// ControllerSnapshotRecord Serialization Tests
// =============================================================================
TEST_CASE("ControllerSnapshotRecord serialization and deserialization", "[controller][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create controller snapshot
    core::Point left_pos(1.0f, 2.0f, 3.0f);
    core::Quaternion left_orient(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose left_p(left_pos, left_orient);
    core::ControllerPose left_grip(left_p, true);
    core::ControllerInputState left_inputs(true, false, false, 0.5f, 0.0f, 0.5f, 0.5f);
    core::ControllerSnapshot snapshot(left_grip, left_grip, left_inputs, true);

    // Create record with data and timestamp
    core::ControllerSnapshotRecordT record;
    record.data = std::make_unique<core::ControllerSnapshot>(snapshot);
    record.timestamp = std::make_unique<core::DeviceDataTimestamp>(1000, 2000, 0);

    // Serialize
    auto offset = core::ControllerSnapshotRecord::Pack(builder, &record);
    builder.Finish(offset);

    // Deserialize
    auto* deserialized = flatbuffers::GetRoot<core::ControllerSnapshotRecord>(builder.GetBufferPointer());

    // Verify
    REQUIRE(deserialized->data() != nullptr);
    CHECK(deserialized->data()->is_active() == true);
    CHECK(deserialized->data()->inputs().primary_click() == true);
    REQUIRE(deserialized->timestamp() != nullptr);
    CHECK(deserialized->timestamp()->sample_time_device_clock() == 1000);
}

TEST_CASE("ControllerSnapshotRecord can be unpacked from buffer", "[controller][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create native object
    core::ControllerSnapshotRecordT record;
    core::ControllerSnapshot snapshot;
    record.data = std::make_unique<core::ControllerSnapshot>(snapshot);
    record.timestamp = std::make_unique<core::DeviceDataTimestamp>(0, 0, 0);

    // Serialize
    auto offset = core::ControllerSnapshotRecord::Pack(builder, &record);
    builder.Finish(offset);

    // Deserialize to table
    auto* table = flatbuffers::GetRoot<core::ControllerSnapshotRecord>(builder.GetBufferPointer());

    // Unpack to native
    auto unpacked = std::make_unique<core::ControllerSnapshotRecordT>();
    table->UnPackTo(unpacked.get());

    // Verify
    CHECK(unpacked->data != nullptr);
}
