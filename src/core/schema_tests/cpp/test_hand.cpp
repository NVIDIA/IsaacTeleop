// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated HandPose FlatBuffer message.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/hand_generated.h>

#include <memory>
#include <type_traits>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs.
// These ensure schema field IDs remain stable across changes.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2
static_assert(core::HandPose::VT_JOINTS == VT(0));
static_assert(core::HandPose::VT_IS_ACTIVE == VT(1));
static_assert(core::HandPose::VT_TIMESTAMP == VT(2));

// =============================================================================
// Compile-time verification of FlatBuffer field types.
// These ensure schema field types remain stable across changes.
// =============================================================================
#define TYPE(field) decltype(std::declval<core::HandPose>().field())
static_assert(std::is_same_v<TYPE(joints), const core::HandJoints*>);
static_assert(std::is_same_v<TYPE(is_active), bool>);
static_assert(std::is_same_v<TYPE(timestamp), int64_t>);

// =============================================================================
// Compile-time verification of HandJointPose struct.
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::HandJointPose>, "HandJointPose should be a trivially copyable struct");

// =============================================================================
// Compile-time verification of HandJoints struct.
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::HandJoints>, "HandJoints should be a trivially copyable struct");

// HandJoints should contain exactly 26 HandJointPose entries.
static_assert(sizeof(core::HandJoints) == 26 * sizeof(core::HandJointPose),
              "HandJoints should contain exactly 26 HandJointPose entries");

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
// HandJoints Tests
// =============================================================================
TEST_CASE("HandJoints struct has correct size", "[hand][struct]")
{
    // HandJoints should have exactly 26 entries (XR_HAND_JOINT_COUNT_EXT).
    core::HandJoints joints;
    CHECK(joints.poses()->size() == 26);
}

TEST_CASE("HandJoints can be accessed by index", "[hand][struct]")
{
    core::HandJoints joints;

    // Access first and last entries (returns pointers).
    const auto* first = (*joints.poses())[0];
    const auto* last = (*joints.poses())[25];

    // Default values should be zero.
    CHECK(first->pose().position().x() == 0.0f);
    CHECK(last->pose().position().x() == 0.0f);
}

// =============================================================================
// HandPoseT Tests
// =============================================================================
TEST_CASE("HandPoseT can handle is_active value properly", "[hand][native]")
{
    // Create HandPoseT with default values, is_active should be false.
    auto hand_pose = std::make_unique<core::HandPoseT>();
    CHECK(hand_pose->is_active == false);

    // Set is_active to true.
    hand_pose->is_active = true;
    CHECK(hand_pose->is_active == true);
}

TEST_CASE("HandPoseT default construction", "[hand][native]")
{
    auto hand_pose = std::make_unique<core::HandPoseT>();

    // Default values.
    CHECK(hand_pose->joints == nullptr);
    CHECK(hand_pose->is_active == false);
    CHECK(hand_pose->timestamp == 0);
}

TEST_CASE("HandPoseT can store joints data", "[hand][native]")
{
    auto hand_pose = std::make_unique<core::HandPoseT>();

    // Create and set joints.
    hand_pose->joints = std::make_unique<core::HandJoints>();

    // Verify joints are set.
    REQUIRE(hand_pose->joints != nullptr);
    CHECK(hand_pose->joints->poses()->size() == 26);
}

TEST_CASE("HandPoseT can store timestamp", "[hand][native]")
{
    auto hand_pose = std::make_unique<core::HandPoseT>();

    // Set timestamp (XrTime is int64_t).
    int64_t test_timestamp = 1234567890123456789LL;
    hand_pose->timestamp = test_timestamp;

    CHECK(hand_pose->timestamp == test_timestamp);
}

TEST_CASE("HandPoseT joints can be mutated via flatbuffers Array", "[hand][native]")
{
    auto hand_pose = std::make_unique<core::HandPoseT>();
    hand_pose->joints = std::make_unique<core::HandJoints>();

    // Create a joint pose.
    core::Point position(1.0f, 2.0f, 3.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    core::HandJointPose joint_pose(pose, true, 0.015f);

    // Mutate first joint using const_cast (FlatBuffers struct mutation).
    auto* mutable_array = const_cast<flatbuffers::Array<core::HandJointPose, 26>*>(hand_pose->joints->poses());
    mutable_array->Mutate(0, joint_pose);

    // Verify.
    const auto* first_joint = (*hand_pose->joints->poses())[0];
    CHECK(first_joint->pose().position().x() == 1.0f);
    CHECK(first_joint->pose().position().y() == 2.0f);
    CHECK(first_joint->pose().position().z() == 3.0f);
    CHECK(first_joint->is_valid() == true);
    CHECK(first_joint->radius() == Catch::Approx(0.015f));
}

TEST_CASE("HandPoseT serialization and deserialization", "[hand][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(4096);

    // Create HandPoseT with all fields set.
    auto hand_pose = std::make_unique<core::HandPoseT>();
    hand_pose->joints = std::make_unique<core::HandJoints>();

    // Set a few joint poses using const_cast.
    core::Point position(1.5f, 2.5f, 3.5f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    core::HandJointPose joint_pose(pose, true, 0.02f);

    auto* mutable_array = const_cast<flatbuffers::Array<core::HandJointPose, 26>*>(hand_pose->joints->poses());
    mutable_array->Mutate(0, joint_pose);

    hand_pose->is_active = true;
    hand_pose->timestamp = 9876543210LL;

    // Serialize.
    auto offset = core::HandPose::Pack(builder, hand_pose.get());
    builder.Finish(offset);

    // Deserialize.
    auto buffer = builder.GetBufferPointer();
    auto deserialized = core::GetHandPose(buffer);

    // Verify.
    REQUIRE(deserialized->joints() != nullptr);
    CHECK(deserialized->joints()->poses()->size() == 26);

    const auto* first_joint = (*deserialized->joints()->poses())[0];
    CHECK(first_joint->pose().position().x() == Catch::Approx(1.5f));
    CHECK(first_joint->pose().position().y() == Catch::Approx(2.5f));
    CHECK(first_joint->pose().position().z() == Catch::Approx(3.5f));
    CHECK(first_joint->is_valid() == true);
    CHECK(first_joint->radius() == Catch::Approx(0.02f));

    CHECK(deserialized->is_active() == true);
    CHECK(deserialized->timestamp() == 9876543210LL);
}

TEST_CASE("HandPoseT can be unpacked from buffer", "[hand][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(4096);

    // Create and serialize.
    auto original = std::make_unique<core::HandPoseT>();
    original->joints = std::make_unique<core::HandJoints>();

    // Set multiple joint poses.
    auto* mutable_array = const_cast<flatbuffers::Array<core::HandJointPose, 26>*>(original->joints->poses());
    for (size_t i = 0; i < 26; ++i)
    {
        core::Point position(static_cast<float>(i), static_cast<float>(i * 2), static_cast<float>(i * 3));
        core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
        core::Pose pose(position, orientation);
        core::HandJointPose joint_pose(pose, true, 0.01f + static_cast<float>(i) * 0.001f);
        mutable_array->Mutate(i, joint_pose);
    }

    original->is_active = true;
    original->timestamp = 1111111111LL;

    auto offset = core::HandPose::Pack(builder, original.get());
    builder.Finish(offset);

    // Unpack to HandPoseT.
    auto buffer = builder.GetBufferPointer();
    auto hand_pose_fb = core::GetHandPose(buffer);
    auto unpacked = std::make_unique<core::HandPoseT>();
    hand_pose_fb->UnPackTo(unpacked.get());

    // Verify unpacked data.
    REQUIRE(unpacked->joints != nullptr);

    // Check a few joints.
    const auto* joint_5 = (*unpacked->joints->poses())[5];
    CHECK(joint_5->pose().position().x() == Catch::Approx(5.0f));
    CHECK(joint_5->pose().position().y() == Catch::Approx(10.0f));
    CHECK(joint_5->pose().position().z() == Catch::Approx(15.0f));

    const auto* joint_25 = (*unpacked->joints->poses())[25];
    CHECK(joint_25->pose().position().x() == Catch::Approx(25.0f));
    CHECK(joint_25->pose().position().y() == Catch::Approx(50.0f));
    CHECK(joint_25->pose().position().z() == Catch::Approx(75.0f));

    CHECK(unpacked->is_active == true);
    CHECK(unpacked->timestamp == 1111111111LL);
}

TEST_CASE("HandPoseT all 26 joints can be set and verified", "[hand][native]")
{
    auto hand_pose = std::make_unique<core::HandPoseT>();
    hand_pose->joints = std::make_unique<core::HandJoints>();

    // Set all 26 joints with unique positions.
    auto* mutable_array = const_cast<flatbuffers::Array<core::HandJointPose, 26>*>(hand_pose->joints->poses());
    for (size_t i = 0; i < 26; ++i)
    {
        core::Point position(static_cast<float>(i), 0.0f, 0.0f);
        core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
        core::Pose pose(position, orientation);
        core::HandJointPose joint_pose(pose, true, 0.01f);
        mutable_array->Mutate(i, joint_pose);
    }

    // Verify all joints.
    for (size_t i = 0; i < 26; ++i)
    {
        const auto* joint = (*hand_pose->joints->poses())[i];
        CHECK(joint->pose().position().x() == Catch::Approx(static_cast<float>(i)));
        CHECK(joint->is_valid() == true);
    }
}
