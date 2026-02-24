// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated FullBodyPosePico FlatBuffer struct.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/full_body_generated.h>

#include <memory>
#include <type_traits>

// =============================================================================
// Compile-time verification of FullBodyPosePicoRecord field IDs.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2
static_assert(core::FullBodyPosePicoRecord::VT_DATA == VT(0));

// =============================================================================
// Compile-time verification of struct properties.
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::BodyJointPose>, "BodyJointPose should be a trivially copyable struct");
static_assert(std::is_trivially_copyable_v<core::FullBodyPosePico>,
              "FullBodyPosePico should be a trivially copyable struct");

// =============================================================================
// Compile-time verification of BodyJointPico enum.
// =============================================================================
static_assert(core::BodyJointPico_PELVIS == 0, "PELVIS should be index 0");
static_assert(core::BodyJointPico_RIGHT_HAND == 23, "RIGHT_HAND should be index 23");
static_assert(core::BodyJointPico_NUM_JOINTS == 24, "NUM_JOINTS should be 24");

// =============================================================================
// BodyJointPose Tests
// =============================================================================
TEST_CASE("BodyJointPose struct can be created and accessed", "[full_body][struct]")
{
    core::Point position(1.0f, 2.0f, 3.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    core::BodyJointPose joint_pose(pose, true);

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
}

TEST_CASE("BodyJointPose default construction", "[full_body][struct]")
{
    core::BodyJointPose joint_pose;

    // Default values should be zero/false.
    CHECK(joint_pose.pose().position().x() == 0.0f);
    CHECK(joint_pose.pose().position().y() == 0.0f);
    CHECK(joint_pose.pose().position().z() == 0.0f);
    CHECK(joint_pose.is_valid() == false);
}

// =============================================================================
// FullBodyPosePico Struct Tests
// =============================================================================
TEST_CASE("FullBodyPosePico default construction", "[full_body][struct]")
{
    core::FullBodyPosePico body_pose;

    CHECK(body_pose.is_active() == false);
    CHECK(body_pose.timestamp().device_time() == 0);
    CHECK(body_pose.timestamp().common_time() == 0);
    CHECK(body_pose.joints()->size() == static_cast<size_t>(core::BodyJointPico_NUM_JOINTS));
}

TEST_CASE("FullBodyPosePico is_active can be mutated", "[full_body][struct]")
{
    core::FullBodyPosePico body_pose;
    CHECK(body_pose.is_active() == false);

    body_pose.mutate_is_active(true);
    CHECK(body_pose.is_active() == true);
}

TEST_CASE("FullBodyPosePico timestamp can be mutated", "[full_body][struct]")
{
    core::FullBodyPosePico body_pose;

    int64_t test_device_time = 1234567890123456789LL;
    int64_t test_common_time = 9876543210LL;
    body_pose.mutable_timestamp() = core::Timestamp(test_device_time, test_common_time);

    CHECK(body_pose.timestamp().device_time() == test_device_time);
    CHECK(body_pose.timestamp().common_time() == test_common_time);
}

TEST_CASE("FullBodyPosePico joints can be mutated", "[full_body][struct]")
{
    core::FullBodyPosePico body_pose;

    core::Point position(1.0f, 2.0f, 3.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    core::BodyJointPose joint_pose(pose, true);

    body_pose.mutable_joints()->Mutate(0, joint_pose);

    const auto* first_joint = (*body_pose.joints())[0];
    CHECK(first_joint->pose().position().x() == 1.0f);
    CHECK(first_joint->pose().position().y() == 2.0f);
    CHECK(first_joint->pose().position().z() == 3.0f);
    CHECK(first_joint->is_valid() == true);
}

TEST_CASE("FullBodyPosePico all 24 joints can be set and verified", "[full_body][struct]")
{
    core::FullBodyPosePico body_pose;

    for (size_t i = 0; i < 24; ++i)
    {
        core::Point position(static_cast<float>(i), 0.0f, 0.0f);
        core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
        core::Pose pose(position, orientation);
        core::BodyJointPose joint_pose(pose, true);
        body_pose.mutable_joints()->Mutate(i, joint_pose);
    }

    for (size_t i = 0; i < 24; ++i)
    {
        const auto* joint = (*body_pose.joints())[i];
        CHECK(joint->pose().position().x() == Catch::Approx(static_cast<float>(i)));
        CHECK(joint->is_valid() == true);
    }
}

// =============================================================================
// Body Joint Index Tests (XR_BD_body_tracking joint mapping)
// =============================================================================
TEST_CASE("FullBodyPosePico joint indices correspond to body parts", "[full_body][joints]")
{
    core::FullBodyPosePico body_pose;

    REQUIRE(body_pose.joints()->size() == 24);

    const auto* pelvis = (*body_pose.joints())[0];
    const auto* head = (*body_pose.joints())[15];
    const auto* left_hand = (*body_pose.joints())[22];
    const auto* right_hand = (*body_pose.joints())[23];

    CHECK(pelvis != nullptr);
    CHECK(head != nullptr);
    CHECK(left_hand != nullptr);
    CHECK(right_hand != nullptr);
}

// =============================================================================
// Edge Cases
// =============================================================================
TEST_CASE("FullBodyPosePico with large timestamp values", "[full_body][edge]")
{
    core::FullBodyPosePico body_pose;
    int64_t max_int64 = 9223372036854775807LL;
    body_pose.mutable_timestamp() = core::Timestamp(max_int64, max_int64 - 1000);

    CHECK(body_pose.timestamp().device_time() == max_int64);
    CHECK(body_pose.timestamp().common_time() == max_int64 - 1000);
}

TEST_CASE("FullBodyPosePico struct size is reasonable", "[full_body][struct]")
{
    // Each BodyJointPose is Pose (28 bytes) + bool (1 byte with padding) = 32 bytes.
    // 24 joints * 32 bytes = 768 bytes, plus is_active + timestamp + padding.
    CHECK(sizeof(core::FullBodyPosePico) == 792);
}

// =============================================================================
// BodyJointPico Enum Tests
// =============================================================================
TEST_CASE("BodyJointPico enum has correct values", "[full_body][enum]")
{
    CHECK(core::BodyJointPico_PELVIS == 0);
    CHECK(core::BodyJointPico_LEFT_HIP == 1);
    CHECK(core::BodyJointPico_RIGHT_HIP == 2);
    CHECK(core::BodyJointPico_SPINE1 == 3);
    CHECK(core::BodyJointPico_LEFT_KNEE == 4);
    CHECK(core::BodyJointPico_RIGHT_KNEE == 5);
    CHECK(core::BodyJointPico_SPINE2 == 6);
    CHECK(core::BodyJointPico_LEFT_ANKLE == 7);
    CHECK(core::BodyJointPico_RIGHT_ANKLE == 8);
    CHECK(core::BodyJointPico_SPINE3 == 9);
    CHECK(core::BodyJointPico_LEFT_FOOT == 10);
    CHECK(core::BodyJointPico_RIGHT_FOOT == 11);
    CHECK(core::BodyJointPico_NECK == 12);
    CHECK(core::BodyJointPico_LEFT_COLLAR == 13);
    CHECK(core::BodyJointPico_RIGHT_COLLAR == 14);
    CHECK(core::BodyJointPico_HEAD == 15);
    CHECK(core::BodyJointPico_LEFT_SHOULDER == 16);
    CHECK(core::BodyJointPico_RIGHT_SHOULDER == 17);
    CHECK(core::BodyJointPico_LEFT_ELBOW == 18);
    CHECK(core::BodyJointPico_RIGHT_ELBOW == 19);
    CHECK(core::BodyJointPico_LEFT_WRIST == 20);
    CHECK(core::BodyJointPico_RIGHT_WRIST == 21);
    CHECK(core::BodyJointPico_LEFT_HAND == 22);
    CHECK(core::BodyJointPico_RIGHT_HAND == 23);
    CHECK(core::BodyJointPico_NUM_JOINTS == 24);
}

TEST_CASE("BodyJointPico enum can index FullBodyPosePico joints", "[full_body][enum]")
{
    core::FullBodyPosePico body_pose;

    core::Point head_position(0.0f, 1.7f, 0.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose head_pose(head_position, orientation);
    core::BodyJointPose head_joint(head_pose, true);
    body_pose.mutable_joints()->Mutate(core::BodyJointPico_HEAD, head_joint);

    core::Point left_hand_position(-0.5f, 1.0f, 0.3f);
    core::Pose left_hand_pose(left_hand_position, orientation);
    core::BodyJointPose left_hand_joint(left_hand_pose, true);
    body_pose.mutable_joints()->Mutate(core::BodyJointPico_LEFT_HAND, left_hand_joint);

    const auto* head = (*body_pose.joints())[core::BodyJointPico_HEAD];
    CHECK(head->pose().position().y() == Catch::Approx(1.7f));
    CHECK(head->is_valid() == true);

    const auto* left_hand = (*body_pose.joints())[core::BodyJointPico_LEFT_HAND];
    CHECK(left_hand->pose().position().x() == Catch::Approx(-0.5f));
    CHECK(left_hand->is_valid() == true);
}
