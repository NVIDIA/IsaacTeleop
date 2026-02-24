// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated Locomotion FlatBuffer types.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/locomotion_generated.h>

#include <type_traits>

// =============================================================================
// Compile-time verification that Twist is a struct (not a table).
// Structs are fixed-size, inline types in FlatBuffers.
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::Twist>, "Twist should be a trivially copyable struct");
static_assert(sizeof(core::Twist) == 2 * sizeof(core::Point), "Twist size should be 2 Points (linear + angular)");

// =============================================================================
// Compile-time verification of struct member types.
// =============================================================================
static_assert(std::is_same_v<decltype(std::declval<core::Twist>().linear()), const core::Point&>);
static_assert(std::is_same_v<decltype(std::declval<core::Twist>().angular()), const core::Point&>);

// =============================================================================
// Compile-time verification of FlatBuffer field IDs for LocomotionCommand table.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2

static_assert(core::LocomotionCommand::VT_TIMESTAMP == VT(0));
static_assert(core::LocomotionCommand::VT_VELOCITY == VT(1));
static_assert(core::LocomotionCommand::VT_POSE == VT(2));
static_assert(core::LocomotionCommand::VT_VELOCITY_VALID == VT(3));
static_assert(core::LocomotionCommand::VT_POSE_VALID == VT(4));

static_assert(core::LocomotionCommandRecord::VT_DATA == VT(0));

// =============================================================================
// Twist Tests (struct)
// =============================================================================
TEST_CASE("Twist struct can be created and accessed", "[locomotion][twist][struct]")
{
    core::Point linear(1.0f, 2.0f, 0.0f); // Forward + left velocity
    core::Point angular(0.0f, 0.0f, 0.5f); // Yaw rotation
    core::Twist twist(linear, angular);

    SECTION("Linear velocity values are accessible")
    {
        CHECK(twist.linear().x() == 1.0f);
        CHECK(twist.linear().y() == 2.0f);
        CHECK(twist.linear().z() == 0.0f);
    }

    SECTION("Angular velocity values are accessible")
    {
        CHECK(twist.angular().x() == 0.0f);
        CHECK(twist.angular().y() == 0.0f);
        CHECK(twist.angular().z() == 0.5f);
    }
}

TEST_CASE("Twist struct default construction", "[locomotion][twist][struct]")
{
    core::Twist twist{};

    CHECK(twist.linear().x() == 0.0f);
    CHECK(twist.linear().y() == 0.0f);
    CHECK(twist.linear().z() == 0.0f);
    CHECK(twist.angular().x() == 0.0f);
    CHECK(twist.angular().y() == 0.0f);
    CHECK(twist.angular().z() == 0.0f);
}

TEST_CASE("Twist struct with negative velocities", "[locomotion][twist][struct]")
{
    core::Point linear(-1.5f, -0.5f, 0.0f); // Backward + right velocity
    core::Point angular(0.0f, 0.0f, -0.3f); // Yaw rotation opposite direction
    core::Twist twist(linear, angular);

    CHECK(twist.linear().x() == Catch::Approx(-1.5f));
    CHECK(twist.linear().y() == Catch::Approx(-0.5f));
    CHECK(twist.angular().z() == Catch::Approx(-0.3f));
}

TEST_CASE("Twist struct is trivially copyable", "[locomotion][twist][struct]")
{
    core::Point linear(1.0f, 2.0f, 3.0f);
    core::Point angular(0.1f, 0.2f, 0.3f);
    core::Twist twist1(linear, angular);

    // Copy the twist.
    core::Twist twist2 = twist1;

    // Verify the copy has the same values.
    CHECK(twist2.linear().x() == twist1.linear().x());
    CHECK(twist2.linear().y() == twist1.linear().y());
    CHECK(twist2.linear().z() == twist1.linear().z());
    CHECK(twist2.angular().x() == twist1.angular().x());
    CHECK(twist2.angular().y() == twist1.angular().y());
    CHECK(twist2.angular().z() == twist1.angular().z());
}

// =============================================================================
// LocomotionCommandT Tests (table native type)
// =============================================================================
TEST_CASE("LocomotionCommandT default construction", "[locomotion][native]")
{
    core::LocomotionCommandT cmd;

    // Table fields default to nullptr; booleans default to false.
    CHECK(cmd.timestamp == nullptr);
    CHECK(cmd.velocity == nullptr);
    CHECK(cmd.pose == nullptr);
    CHECK(cmd.velocity_valid == false);
    CHECK(cmd.pose_valid == false);
}

TEST_CASE("LocomotionCommandT velocity mode", "[locomotion][native]")
{
    core::LocomotionCommandT cmd;
    cmd.timestamp = std::make_shared<core::Timestamp>(1000000000, 2000000000);

    core::Point linear(1.0f, 0.0f, 0.0f);
    core::Point angular(0.0f, 0.0f, 0.5f);
    cmd.velocity = std::make_shared<core::Twist>(linear, angular);
    cmd.velocity_valid = true;

    core::Point zero_pos(0.0f, 0.0f, 0.0f);
    core::Quaternion identity(0.0f, 0.0f, 0.0f, 1.0f);
    cmd.pose = std::make_shared<core::Pose>(zero_pos, identity);
    cmd.pose_valid = false;

    CHECK(cmd.timestamp->device_time() == 1000000000);
    CHECK(cmd.velocity->linear().x() == Catch::Approx(1.0f));
    CHECK(cmd.velocity->angular().z() == Catch::Approx(0.5f));
    CHECK(cmd.velocity_valid == true);
    CHECK(cmd.pose_valid == false);
}

TEST_CASE("LocomotionCommandT pose mode", "[locomotion][native]")
{
    core::LocomotionCommandT cmd;
    cmd.timestamp = std::make_shared<core::Timestamp>(3000000000, 4000000000);

    core::Point zero_linear(0.0f, 0.0f, 0.0f);
    cmd.velocity = std::make_shared<core::Twist>(zero_linear, zero_linear);
    cmd.velocity_valid = false;

    core::Point position(0.0f, 0.0f, -0.2f); // Squat down.
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    cmd.pose = std::make_shared<core::Pose>(position, orientation);
    cmd.pose_valid = true;

    CHECK(cmd.pose->position().z() == Catch::Approx(-0.2f));
    CHECK(cmd.pose_valid == true);
    CHECK(cmd.velocity_valid == false);
}

// =============================================================================
// LocomotionCommand Serialization Tests
// =============================================================================
TEST_CASE("LocomotionCommand serialization and deserialization", "[locomotion][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::LocomotionCommandT cmd;
    cmd.timestamp = std::make_shared<core::Timestamp>(1234567890, 9876543210);

    core::Point linear(2.0f, 1.0f, 0.0f);
    core::Point angular(0.0f, 0.0f, 0.75f);
    cmd.velocity = std::make_shared<core::Twist>(linear, angular);
    cmd.velocity_valid = true;

    core::Point position(0.0f, 0.0f, 0.05f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    cmd.pose = std::make_shared<core::Pose>(position, orientation);
    cmd.pose_valid = false;

    auto offset = core::LocomotionCommand::Pack(builder, &cmd);
    builder.Finish(offset);

    auto* deserialized = flatbuffers::GetRoot<core::LocomotionCommand>(builder.GetBufferPointer());

    REQUIRE(deserialized->timestamp() != nullptr);
    CHECK(deserialized->timestamp()->device_time() == 1234567890);
    CHECK(deserialized->timestamp()->common_time() == 9876543210);

    REQUIRE(deserialized->velocity() != nullptr);
    CHECK(deserialized->velocity()->linear().x() == Catch::Approx(2.0f));
    CHECK(deserialized->velocity()->linear().y() == Catch::Approx(1.0f));
    CHECK(deserialized->velocity()->angular().z() == Catch::Approx(0.75f));
    CHECK(deserialized->velocity_valid() == true);

    REQUIRE(deserialized->pose() != nullptr);
    CHECK(deserialized->pose()->position().z() == Catch::Approx(0.05f));
    CHECK(deserialized->pose()->orientation().w() == Catch::Approx(1.0f));
    CHECK(deserialized->pose_valid() == false);
}

TEST_CASE("LocomotionCommand can be unpacked from buffer", "[locomotion][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::LocomotionCommandT cmd;
    cmd.timestamp = std::make_shared<core::Timestamp>(100, 200);
    core::Point zero(0.0f, 0.0f, 0.0f);
    cmd.velocity = std::make_shared<core::Twist>(zero, zero);
    cmd.pose = std::make_shared<core::Pose>(zero, core::Quaternion(0.0f, 0.0f, 0.0f, 1.0f));
    cmd.velocity_valid = false;
    cmd.pose_valid = false;

    auto offset = core::LocomotionCommand::Pack(builder, &cmd);
    builder.Finish(offset);

    auto* table = flatbuffers::GetRoot<core::LocomotionCommand>(builder.GetBufferPointer());

    auto unpacked = std::make_unique<core::LocomotionCommandT>();
    table->UnPackTo(unpacked.get());

    CHECK(unpacked->timestamp->device_time() == 100);
    CHECK(unpacked->timestamp->common_time() == 200);
    CHECK(unpacked->velocity_valid == false);
    CHECK(unpacked->pose_valid == false);
}

TEST_CASE("LocomotionCommand velocity mode roundtrip", "[locomotion][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::LocomotionCommandT cmd;
    cmd.timestamp = std::make_shared<core::Timestamp>(1000, 2000);

    core::Point linear(1.0f, 0.0f, 0.0f);
    core::Point angular(0.0f, 0.0f, 0.0f);
    cmd.velocity = std::make_shared<core::Twist>(linear, angular);
    cmd.velocity_valid = true;

    core::Point zero(0.0f, 0.0f, 0.0f);
    cmd.pose = std::make_shared<core::Pose>(zero, core::Quaternion(0.0f, 0.0f, 0.0f, 1.0f));
    cmd.pose_valid = false;

    auto offset = core::LocomotionCommand::Pack(builder, &cmd);
    builder.Finish(offset);

    auto* deserialized = flatbuffers::GetRoot<core::LocomotionCommand>(builder.GetBufferPointer());

    REQUIRE(deserialized->velocity() != nullptr);
    CHECK(deserialized->velocity()->linear().x() == Catch::Approx(1.0f));
    CHECK(deserialized->velocity_valid() == true);

    REQUIRE(deserialized->pose() != nullptr);
    CHECK(deserialized->pose_valid() == false);
}

TEST_CASE("LocomotionCommand pose mode roundtrip", "[locomotion][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::LocomotionCommandT cmd;
    cmd.timestamp = std::make_shared<core::Timestamp>(3000, 4000);

    core::Point zero(0.0f, 0.0f, 0.0f);
    cmd.velocity = std::make_shared<core::Twist>(zero, zero);
    cmd.velocity_valid = false;

    core::Point position(0.0f, 0.0f, -0.1f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    cmd.pose = std::make_shared<core::Pose>(position, orientation);
    cmd.pose_valid = true;

    auto offset = core::LocomotionCommand::Pack(builder, &cmd);
    builder.Finish(offset);

    auto* deserialized = flatbuffers::GetRoot<core::LocomotionCommand>(builder.GetBufferPointer());

    REQUIRE(deserialized->velocity() != nullptr);
    CHECK(deserialized->velocity_valid() == false);

    REQUIRE(deserialized->pose() != nullptr);
    CHECK(deserialized->pose()->position().z() == Catch::Approx(-0.1f));
    CHECK(deserialized->pose_valid() == true);
}

// =============================================================================
// Edge Cases
// =============================================================================
TEST_CASE("Twist with zero values", "[locomotion][twist][edge]")
{
    core::Point zero(0.0f, 0.0f, 0.0f);
    core::Twist twist(zero, zero);

    CHECK(twist.linear().x() == 0.0f);
    CHECK(twist.linear().y() == 0.0f);
    CHECK(twist.linear().z() == 0.0f);
    CHECK(twist.angular().x() == 0.0f);
    CHECK(twist.angular().y() == 0.0f);
    CHECK(twist.angular().z() == 0.0f);
}

TEST_CASE("Twist with maximum float values", "[locomotion][twist][edge]")
{
    float max_vel = 10.0f; // Reasonable max velocity for robot.
    core::Point linear(max_vel, max_vel, max_vel);
    core::Point angular(max_vel, max_vel, max_vel);
    core::Twist twist(linear, angular);

    CHECK(twist.linear().x() == Catch::Approx(max_vel));
    CHECK(twist.angular().z() == Catch::Approx(max_vel));
}

TEST_CASE("LocomotionCommand buffer size is reasonable", "[locomotion][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::LocomotionCommandT cmd;
    cmd.timestamp = std::make_shared<core::Timestamp>(0, 0);

    core::Point zero(0.0f, 0.0f, 0.0f);
    cmd.velocity = std::make_shared<core::Twist>(zero, zero);
    cmd.pose = std::make_shared<core::Pose>(zero, core::Quaternion(0.0f, 0.0f, 0.0f, 1.0f));
    cmd.velocity_valid = false;
    cmd.pose_valid = false;

    auto offset = core::LocomotionCommand::Pack(builder, &cmd);
    builder.Finish(offset);

    // Buffer should be reasonably small (under 256 bytes for this simple message).
    CHECK(builder.GetSize() < 256);
}
