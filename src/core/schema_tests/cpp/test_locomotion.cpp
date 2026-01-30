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

    // Struct pointers should be null by default for table fields.
    CHECK(cmd.timestamp == nullptr);
    CHECK(cmd.velocity == nullptr);
    CHECK(cmd.pose == nullptr);
}

TEST_CASE("LocomotionCommandT can store velocity command", "[locomotion][native]")
{
    core::LocomotionCommandT cmd;

    // Create timestamp.
    cmd.timestamp = std::make_unique<core::Timestamp>(1000000000, 2000000000);

    // Create velocity (twist).
    core::Point linear(1.0f, 0.0f, 0.0f);
    core::Point angular(0.0f, 0.0f, 0.5f);
    cmd.velocity = std::make_unique<core::Twist>(linear, angular);

    CHECK(cmd.timestamp != nullptr);
    CHECK(cmd.timestamp->device_time() == 1000000000);
    CHECK(cmd.timestamp->common_time() == 2000000000);
    CHECK(cmd.velocity != nullptr);
    CHECK(cmd.velocity->linear().x() == Catch::Approx(1.0f));
    CHECK(cmd.velocity->angular().z() == Catch::Approx(0.5f));
    CHECK(cmd.pose == nullptr); // Pose not set.
}

TEST_CASE("LocomotionCommandT can store pose command", "[locomotion][native]")
{
    core::LocomotionCommandT cmd;

    // Create timestamp.
    cmd.timestamp = std::make_unique<core::Timestamp>(3000000000, 4000000000);

    // Create pose (for squat/vertical mode).
    core::Point position(0.0f, 0.0f, -0.2f); // Squat down.
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    cmd.pose = std::make_unique<core::Pose>(position, orientation);

    CHECK(cmd.timestamp != nullptr);
    CHECK(cmd.pose != nullptr);
    CHECK(cmd.pose->position().z() == Catch::Approx(-0.2f));
    CHECK(cmd.velocity == nullptr); // Velocity not set.
}

TEST_CASE("LocomotionCommandT can store both velocity and pose", "[locomotion][native]")
{
    core::LocomotionCommandT cmd;

    // Create timestamp.
    cmd.timestamp = std::make_unique<core::Timestamp>(5000000000, 6000000000);

    // Create velocity.
    core::Point linear(0.5f, 0.0f, 0.0f);
    core::Point angular(0.0f, 0.0f, 0.1f);
    cmd.velocity = std::make_unique<core::Twist>(linear, angular);

    // Create pose.
    core::Point position(0.0f, 0.0f, 0.1f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    cmd.pose = std::make_unique<core::Pose>(position, orientation);

    CHECK(cmd.timestamp != nullptr);
    CHECK(cmd.velocity != nullptr);
    CHECK(cmd.pose != nullptr);
}

// =============================================================================
// LocomotionCommand Serialization Tests
// =============================================================================
TEST_CASE("LocomotionCommand serialization and deserialization", "[locomotion][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create native object.
    core::LocomotionCommandT cmd;
    cmd.timestamp = std::make_unique<core::Timestamp>(1234567890, 9876543210);

    core::Point linear(2.0f, 1.0f, 0.0f);
    core::Point angular(0.0f, 0.0f, 0.75f);
    cmd.velocity = std::make_unique<core::Twist>(linear, angular);

    core::Point position(0.0f, 0.0f, 0.05f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    cmd.pose = std::make_unique<core::Pose>(position, orientation);

    // Serialize.
    auto offset = core::LocomotionCommand::Pack(builder, &cmd);
    builder.Finish(offset);

    // Deserialize.
    auto* deserialized = flatbuffers::GetRoot<core::LocomotionCommand>(builder.GetBufferPointer());

    // Verify timestamp.
    REQUIRE(deserialized->timestamp() != nullptr);
    CHECK(deserialized->timestamp()->device_time() == 1234567890);
    CHECK(deserialized->timestamp()->common_time() == 9876543210);

    // Verify velocity.
    REQUIRE(deserialized->velocity() != nullptr);
    CHECK(deserialized->velocity()->linear().x() == Catch::Approx(2.0f));
    CHECK(deserialized->velocity()->linear().y() == Catch::Approx(1.0f));
    CHECK(deserialized->velocity()->angular().z() == Catch::Approx(0.75f));

    // Verify pose.
    REQUIRE(deserialized->pose() != nullptr);
    CHECK(deserialized->pose()->position().z() == Catch::Approx(0.05f));
    CHECK(deserialized->pose()->orientation().w() == Catch::Approx(1.0f));
}

TEST_CASE("LocomotionCommand can be unpacked from buffer", "[locomotion][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    // Create native object with minimal data.
    core::LocomotionCommandT cmd;
    cmd.timestamp = std::make_unique<core::Timestamp>(100, 200);

    // Serialize.
    auto offset = core::LocomotionCommand::Pack(builder, &cmd);
    builder.Finish(offset);

    // Deserialize to table.
    auto* table = flatbuffers::GetRoot<core::LocomotionCommand>(builder.GetBufferPointer());

    // Unpack to native.
    auto unpacked = std::make_unique<core::LocomotionCommandT>();
    table->UnPackTo(unpacked.get());

    // Verify.
    REQUIRE(unpacked->timestamp != nullptr);
    CHECK(unpacked->timestamp->device_time() == 100);
    CHECK(unpacked->timestamp->common_time() == 200);
}

TEST_CASE("LocomotionCommand with only velocity (no pose)", "[locomotion][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::LocomotionCommandT cmd;
    cmd.timestamp = std::make_unique<core::Timestamp>(1000, 2000);

    core::Point linear(1.0f, 0.0f, 0.0f);
    core::Point angular(0.0f, 0.0f, 0.0f);
    cmd.velocity = std::make_unique<core::Twist>(linear, angular);
    // pose is intentionally left null.

    auto offset = core::LocomotionCommand::Pack(builder, &cmd);
    builder.Finish(offset);

    auto* deserialized = flatbuffers::GetRoot<core::LocomotionCommand>(builder.GetBufferPointer());

    REQUIRE(deserialized->velocity() != nullptr);
    CHECK(deserialized->pose() == nullptr);
}

TEST_CASE("LocomotionCommand with only pose (no velocity)", "[locomotion][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    core::LocomotionCommandT cmd;
    cmd.timestamp = std::make_unique<core::Timestamp>(3000, 4000);

    core::Point position(0.0f, 0.0f, -0.1f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    cmd.pose = std::make_unique<core::Pose>(position, orientation);
    // velocity is intentionally left null.

    auto offset = core::LocomotionCommand::Pack(builder, &cmd);
    builder.Finish(offset);

    auto* deserialized = flatbuffers::GetRoot<core::LocomotionCommand>(builder.GetBufferPointer());

    CHECK(deserialized->velocity() == nullptr);
    REQUIRE(deserialized->pose() != nullptr);
    CHECK(deserialized->pose()->position().z() == Catch::Approx(-0.1f));
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
    cmd.timestamp = std::make_unique<core::Timestamp>(0, 0);

    core::Point linear(0.0f, 0.0f, 0.0f);
    core::Point angular(0.0f, 0.0f, 0.0f);
    cmd.velocity = std::make_unique<core::Twist>(linear, angular);

    core::Point position(0.0f, 0.0f, 0.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    cmd.pose = std::make_unique<core::Pose>(position, orientation);

    auto offset = core::LocomotionCommand::Pack(builder, &cmd);
    builder.Finish(offset);

    // Buffer should be reasonably small (under 200 bytes for this simple message).
    CHECK(builder.GetSize() < 200);
}
