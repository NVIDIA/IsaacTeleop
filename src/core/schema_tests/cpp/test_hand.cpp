// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated HandPose FlatBuffer struct.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/hand_generated.h>

#include <type_traits>

#define VT(field) (field + 2) * 2
// Only keep Record VT asserts
static_assert(core::HandPoseRecord::VT_DATA == VT(0));
static_assert(std::is_trivially_copyable_v<core::HandPose>);

// =============================================================================
// Compile-time verification of HandJointPose struct.
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::HandJointPose>, "HandJointPose should be a trivially copyable struct");

// =============================================================================
// HandJointPose Tests
// =============================================================================
TEST_CASE("HandJointPose struct can be created and accessed", "[hand][struct]")
{
    core::Point position(1.0f, 2.0f, 3.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    core::HandJointPose joint_pose(pose, true, 0.01f);

    SECTION("Pose values are accessible")
    {
        CHECK(joint_pose.pose().position().x() == 1.0f);
        CHECK(joint_pose.pose().position().y() == 2.0f);
        CHECK(joint_pose.pose().position().z() == 3.0f);
    }

    SECTION("is_valid is accessible")
    {
        CHECK(joint_pose.is_valid() == true);
    }

    SECTION("radius is accessible")
    {
        CHECK(joint_pose.radius() == Catch::Approx(0.01f));
    }
}

TEST_CASE("HandJointPose default construction", "[hand][struct]")
{
    core::HandJointPose joint_pose;

    // Default values should be zero/false.
    CHECK(joint_pose.pose().position().x() == 0.0f);
    CHECK(joint_pose.pose().position().y() == 0.0f);
    CHECK(joint_pose.pose().position().z() == 0.0f);
    CHECK(joint_pose.is_valid() == false);
    CHECK(joint_pose.radius() == 0.0f);
}

// =============================================================================
// HandPose Tests
// =============================================================================
TEST_CASE("HandPose can handle is_active value properly", "[hand][native]")
{
    // Create HandPose with default values, is_active should be false.
    core::HandPose hand_pose;
    CHECK(hand_pose.is_active() == false);

    // Set is_active to true.
    hand_pose.mutate_is_active(true);
    CHECK(hand_pose.is_active() == true);
}

TEST_CASE("HandPose default construction", "[hand][native]")
{
    core::HandPose hand_pose;

    // Default values.
    CHECK(hand_pose.is_active() == false);
    // Struct fields are always present (no null checks needed)
}

TEST_CASE("HandPose joints array has correct size", "[hand][native]")
{
    core::HandPose hand_pose;

    // HandPose should have exactly 26 joints (XR_HAND_JOINT_COUNT_EXT).
    CHECK(hand_pose.joints()->size() == 26);
}

TEST_CASE("HandPose can store timestamp", "[hand][native]")
{
    core::HandPose hand_pose;

    // Set timestamp (XrTime is int64_t).
    int64_t test_device_time = 1234567890123456789LL;
    int64_t test_common_time = 9876543210LL;
    core::Timestamp timestamp(test_device_time, test_common_time);
    hand_pose.mutable_timestamp() = timestamp;

    CHECK(hand_pose.timestamp().device_time() == test_device_time);
    CHECK(hand_pose.timestamp().common_time() == test_common_time);
}

TEST_CASE("HandPose joints can be mutated via flatbuffers Array", "[hand][native]")
{
    core::HandPose hand_pose;

    // Create a joint pose.
    core::Point position(1.0f, 2.0f, 3.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    core::HandJointPose joint_pose(pose, true, 0.015f);

    // Mutate first joint
    hand_pose.mutable_joints()->Mutate(0, joint_pose);

    // Verify.
    const auto* first_joint = (*hand_pose.joints())[0];
    CHECK(first_joint->pose().position().x() == 1.0f);
    CHECK(first_joint->pose().position().y() == 2.0f);
    CHECK(first_joint->pose().position().z() == 3.0f);
    CHECK(first_joint->is_valid() == true);
    CHECK(first_joint->radius() == Catch::Approx(0.015f));
}

TEST_CASE("HandPose all 26 joints can be set and verified", "[hand][native]")
{
    core::HandPose hand_pose;

    // Set all 26 joints with unique positions.
    for (size_t i = 0; i < 26; ++i)
    {
        core::Point position(static_cast<float>(i), 0.0f, 0.0f);
        core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
        core::Pose pose(position, orientation);
        core::HandJointPose joint_pose(pose, true, 0.01f);
        hand_pose.mutable_joints()->Mutate(i, joint_pose);
    }

    // Verify all joints.
    for (size_t i = 0; i < 26; ++i)
    {
        const auto* joint = (*hand_pose.joints())[i];
        CHECK(joint->pose().position().x() == Catch::Approx(static_cast<float>(i)));
        CHECK(joint->is_valid() == true);
    }
}

TEST_CASE("HandPose can store all fields", "[hand][native]")
{
    core::HandPose hand_pose;

    // Set a few joint poses
    core::Point position(1.5f, 2.5f, 3.5f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    core::HandJointPose joint_pose(pose, true, 0.02f);

    hand_pose.mutable_joints()->Mutate(0, joint_pose);
    hand_pose.mutate_is_active(true);
    core::Timestamp timestamp(9876543210LL, 1234567890LL);
    hand_pose.mutable_timestamp() = timestamp;

    // Verify.
    CHECK(hand_pose.joints()->size() == 26);

    const auto* first_joint = (*hand_pose.joints())[0];
    CHECK(first_joint->pose().position().x() == Catch::Approx(1.5f));
    CHECK(first_joint->pose().position().y() == Catch::Approx(2.5f));
    CHECK(first_joint->pose().position().z() == Catch::Approx(3.5f));
    CHECK(first_joint->is_valid() == true);
    CHECK(first_joint->radius() == Catch::Approx(0.02f));

    CHECK(hand_pose.is_active() == true);
    CHECK(hand_pose.timestamp().device_time() == 9876543210LL);
    CHECK(hand_pose.timestamp().common_time() == 1234567890LL);
}

TEST_CASE("HandPose joints can be accessed by index", "[hand][native]")
{
    core::HandPose hand_pose;

    // Access first and last entries (returns pointers).
    const auto* first = (*hand_pose.joints())[0];
    const auto* last = (*hand_pose.joints())[25];

    // Default values should be zero.
    CHECK(first->pose().position().x() == 0.0f);
    CHECK(last->pose().position().x() == 0.0f);
}
