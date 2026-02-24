// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated LocomotionCommand FlatBuffer struct.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>
#include <schema/locomotion_generated.h>

#include <memory>
#include <type_traits>

#define VT(field) (field + 2) * 2
static_assert(core::LocomotionCommandRecord::VT_DATA == VT(0));
static_assert(std::is_trivially_copyable_v<core::LocomotionCommand>);

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
// LocomotionCommand Tests (struct)
// =============================================================================
TEST_CASE("LocomotionCommand default construction", "[locomotion][struct]")
{
    core::LocomotionCommand cmd{};

    // Struct fields are always present, initialized to default values.
    CHECK(cmd.timestamp().device_time() == 0);
    CHECK(cmd.timestamp().common_time() == 0);
    CHECK(cmd.velocity().linear().x() == 0.0f);
    CHECK(cmd.velocity().angular().z() == 0.0f);
    CHECK(cmd.pose().position().z() == 0.0f);
}

TEST_CASE("LocomotionCommand can store velocity command", "[locomotion][struct]")
{
    core::LocomotionCommand cmd{};

    // Set timestamp.
    cmd.mutable_timestamp() = core::Timestamp(1000000000, 2000000000);

    // Set velocity (twist).
    core::Point linear(1.0f, 0.0f, 0.0f);
    core::Point angular(0.0f, 0.0f, 0.5f);
    cmd.mutable_velocity() = core::Twist(linear, angular);

    CHECK(cmd.timestamp().device_time() == 1000000000);
    CHECK(cmd.timestamp().common_time() == 2000000000);
    CHECK(cmd.velocity().linear().x() == Catch::Approx(1.0f));
    CHECK(cmd.velocity().angular().z() == Catch::Approx(0.5f));
}

TEST_CASE("LocomotionCommand can store pose command", "[locomotion][struct]")
{
    core::LocomotionCommand cmd{};

    // Set timestamp.
    cmd.mutable_timestamp() = core::Timestamp(3000000000, 4000000000);

    // Set pose (for squat/vertical mode).
    core::Point position(0.0f, 0.0f, -0.2f); // Squat down.
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    cmd.mutable_pose() = core::Pose(position, orientation);

    CHECK(cmd.timestamp().device_time() == 3000000000);
    CHECK(cmd.pose().position().z() == Catch::Approx(-0.2f));
}

TEST_CASE("LocomotionCommand can store both velocity and pose", "[locomotion][struct]")
{
    core::LocomotionCommand cmd{};

    // Set timestamp.
    cmd.mutable_timestamp() = core::Timestamp(5000000000, 6000000000);

    // Set velocity.
    core::Point linear(0.5f, 0.0f, 0.0f);
    core::Point angular(0.0f, 0.0f, 0.1f);
    cmd.mutable_velocity() = core::Twist(linear, angular);

    // Set pose.
    core::Point position(0.0f, 0.0f, 0.1f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    cmd.mutable_pose() = core::Pose(position, orientation);

    CHECK(cmd.timestamp().device_time() == 5000000000);
    CHECK(cmd.velocity().linear().x() == Catch::Approx(0.5f));
    CHECK(cmd.pose().position().z() == Catch::Approx(0.1f));
}

TEST_CASE("LocomotionCommand is trivially copyable", "[locomotion][struct]")
{
    core::LocomotionCommand cmd1{};
    cmd1.mutable_timestamp() = core::Timestamp(1234567890, 9876543210);

    core::Point linear(2.0f, 1.0f, 0.0f);
    core::Point angular(0.0f, 0.0f, 0.75f);
    cmd1.mutable_velocity() = core::Twist(linear, angular);

    core::Point position(0.0f, 0.0f, 0.05f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    cmd1.mutable_pose() = core::Pose(position, orientation);

    // Copy the command.
    core::LocomotionCommand cmd2 = cmd1;

    // Verify the copy has the same values.
    CHECK(cmd2.timestamp().device_time() == cmd1.timestamp().device_time());
    CHECK(cmd2.timestamp().common_time() == cmd1.timestamp().common_time());
    CHECK(cmd2.velocity().linear().x() == cmd1.velocity().linear().x());
    CHECK(cmd2.velocity().angular().z() == cmd1.velocity().angular().z());
    CHECK(cmd2.pose().position().z() == cmd1.pose().position().z());
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
