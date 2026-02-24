// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated HeadPose FlatBuffer struct.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/head_generated.h>

#include <type_traits>

#define VT(field) (field + 2) * 2
// Only keep Record VT asserts
static_assert(core::HeadPoseRecord::VT_DATA == VT(0));
static_assert(std::is_trivially_copyable_v<core::HeadPose>);

// =============================================================================
// HeadPose Tests
// =============================================================================
TEST_CASE("HeadPose can handle is_valid value properly", "[head][native]")
{
    // Create HeadPose with default values, is_valid should be false.
    core::HeadPose head_pose;
    CHECK(head_pose.is_valid() == false);

    // Set is_valid to true.
    head_pose.mutate_is_valid(true);
    CHECK(head_pose.is_valid() == true);
}

TEST_CASE("HeadPose default construction", "[head][native]")
{
    core::HeadPose head_pose;

    // Default values.
    CHECK(head_pose.is_valid() == false);
    // Struct fields are always present (no null checks needed)
}

TEST_CASE("HeadPose can store pose data", "[head][native]")
{
    core::HeadPose head_pose;

    // Create and set pose.
    core::Point position(1.5f, 2.5f, 3.5f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f); // Identity quaternion.
    core::Pose pose(position, orientation);
    head_pose.mutable_pose() = pose;

    // Verify pose data.
    CHECK(head_pose.pose().position().x() == Catch::Approx(1.5f));
    CHECK(head_pose.pose().position().y() == Catch::Approx(2.5f));
    CHECK(head_pose.pose().position().z() == Catch::Approx(3.5f));
    CHECK(head_pose.pose().orientation().x() == Catch::Approx(0.0f));
    CHECK(head_pose.pose().orientation().y() == Catch::Approx(0.0f));
    CHECK(head_pose.pose().orientation().z() == Catch::Approx(0.0f));
    CHECK(head_pose.pose().orientation().w() == Catch::Approx(1.0f));
}

TEST_CASE("HeadPose can store timestamp", "[head][native]")
{
    core::HeadPose head_pose;

    // Set timestamp (XrTime is int64_t).
    int64_t test_device_time = 1234567890123456789LL;
    int64_t test_common_time = 9876543210LL;
    core::Timestamp timestamp(test_device_time, test_common_time);
    head_pose.mutable_timestamp() = timestamp;

    CHECK(head_pose.timestamp().device_time() == test_device_time);
    CHECK(head_pose.timestamp().common_time() == test_common_time);
}

TEST_CASE("HeadPose can store rotation quaternion", "[head][native]")
{
    core::HeadPose head_pose;

    // 90-degree rotation around Z axis.
    core::Point position(0.0f, 0.0f, 0.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.7071068f, 0.7071068f); // (x, y, z, w)
    core::Pose pose(position, orientation);
    head_pose.mutable_pose() = pose;

    CHECK(head_pose.pose().orientation().z() == Catch::Approx(0.7071068f).epsilon(0.0001));
    CHECK(head_pose.pose().orientation().w() == Catch::Approx(0.7071068f).epsilon(0.0001));
}

TEST_CASE("HeadPose can store all fields", "[head][native]")
{
    core::HeadPose head_pose;

    // Set all fields.
    core::Point position(1.0f, 2.0f, 3.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    head_pose.mutable_pose() = pose;
    head_pose.mutate_is_valid(true);
    core::Timestamp timestamp(9876543210LL, 1234567890LL);
    head_pose.mutable_timestamp() = timestamp;

    // Verify all fields.
    CHECK(head_pose.pose().position().x() == Catch::Approx(1.0f));
    CHECK(head_pose.pose().position().y() == Catch::Approx(2.0f));
    CHECK(head_pose.pose().position().z() == Catch::Approx(3.0f));
    CHECK(head_pose.is_valid() == true);
    CHECK(head_pose.timestamp().device_time() == 9876543210LL);
    CHECK(head_pose.timestamp().common_time() == 1234567890LL);
}
