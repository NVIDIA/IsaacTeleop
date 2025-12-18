// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated Pose FlatBuffer struct.

// Include generated FlatBuffer headers.
#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>
#include <schema/pose_generated.h>

#include <cmath>
#include <type_traits>

// =============================================================================
// Compile-time verification that Pose is a struct (not a table).
// Structs are fixed-size, inline types in FlatBuffers.
// All types (Point, Quaternion, Pose) are in core:: namespace.
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::Pose>, "Pose should be a trivially copyable struct");
static_assert(sizeof(core::Pose) == sizeof(core::Point) + sizeof(core::Quaternion),
              "Pose size should be Point + Quaternion");

// =============================================================================
// Compile-time verification of struct member types.
// =============================================================================
static_assert(std::is_same_v<decltype(std::declval<core::Pose>().position()), const core::Point&>);
static_assert(std::is_same_v<decltype(std::declval<core::Pose>().orientation()), const core::Quaternion&>);

TEST_CASE("Pose struct can be created and accessed", "[pose][struct]")
{
    // Create a Pose struct directly (no builder needed for structs).
    core::Point position(1.5f, 2.5f, 3.5f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f); // Identity quaternion (x, y, z, w)
    core::Pose pose(position, orientation);

    SECTION("Position values are accessible")
    {
        CHECK(pose.position().x() == 1.5f);
        CHECK(pose.position().y() == 2.5f);
        CHECK(pose.position().z() == 3.5f);
    }

    SECTION("Orientation values are accessible")
    {
        CHECK(pose.orientation().x() == 0.0f);
        CHECK(pose.orientation().y() == 0.0f);
        CHECK(pose.orientation().z() == 0.0f);
        CHECK(pose.orientation().w() == 1.0f);
    }
}

TEST_CASE("Pose struct with non-zero position values", "[pose][struct]")
{
    core::Point position(1.5f, 2.5f, 3.5f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);

    CHECK(pose.position().x() == 1.5f);
    CHECK(pose.position().y() == 2.5f);
    CHECK(pose.position().z() == 3.5f);
}

TEST_CASE("Pose struct can store rotation quaternion", "[pose][struct]")
{
    // 90-degree rotation around Z axis: quat(w=0.7071, x=0, y=0, z=0.7071)
    core::Point position(0.0f, 0.0f, 0.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.7071068f, 0.7071068f); // (x, y, z, w)
    core::Pose pose(position, orientation);

    CHECK(pose.orientation().x() == Catch::Approx(0.0f));
    CHECK(pose.orientation().y() == Catch::Approx(0.0f));
    CHECK(pose.orientation().z() == Catch::Approx(0.7071068f).epsilon(0.0001));
    CHECK(pose.orientation().w() == Catch::Approx(0.7071068f).epsilon(0.0001));
}

TEST_CASE("Pose struct is trivially copyable", "[pose][struct]")
{
    core::Point position(1.0f, 2.0f, 3.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose1(position, orientation);

    // Copy the pose.
    core::Pose pose2 = pose1;

    // Verify the copy has the same values.
    CHECK(pose2.position().x() == pose1.position().x());
    CHECK(pose2.position().y() == pose1.position().y());
    CHECK(pose2.position().z() == pose1.position().z());
    CHECK(pose2.orientation().x() == pose1.orientation().x());
    CHECK(pose2.orientation().y() == pose1.orientation().y());
    CHECK(pose2.orientation().z() == pose1.orientation().z());
    CHECK(pose2.orientation().w() == pose1.orientation().w());
}

TEST_CASE("Point struct has correct size and layout", "[pose][point]")
{
    // Point should be 3 floats = 12 bytes.
    static_assert(sizeof(core::Point) == 3 * sizeof(float));

    core::Point point(1.0f, 2.0f, 3.0f);
    CHECK(point.x() == 1.0f);
    CHECK(point.y() == 2.0f);
    CHECK(point.z() == 3.0f);
}

TEST_CASE("Quaternion struct has correct size and layout", "[pose][quaternion]")
{
    // Quaternion should be 4 floats = 16 bytes.
    static_assert(sizeof(core::Quaternion) == 4 * sizeof(float));

    core::Quaternion quat(0.1f, 0.2f, 0.3f, 0.9f); // x, y, z, w
    CHECK(quat.x() == Catch::Approx(0.1f));
    CHECK(quat.y() == Catch::Approx(0.2f));
    CHECK(quat.z() == Catch::Approx(0.3f));
    CHECK(quat.w() == Catch::Approx(0.9f));
}
