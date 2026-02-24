// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated HandPose FlatBuffer message.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/hand_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>
#include <type_traits>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs.
// These ensure schema field IDs remain stable across changes.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2
static_assert(core::HandPose::VT_JOINTS == VT(0));

// =============================================================================
// Compile-time verification of FlatBuffer field types.
// These ensure schema field types remain stable across changes.
// =============================================================================
#define TYPE(field) decltype(std::declval<core::HandPose>().field())
static_assert(std::is_same_v<TYPE(joints), const core::HandJoints*>);

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
TEST_CASE("HandPoseT default construction", "[hand][native]")
{
    auto hand_pose = std::make_unique<core::HandPoseT>();

    // Default values.
    CHECK(hand_pose->joints == nullptr);
}

TEST_CASE("HandPoseT can store joints data", "[hand][native]")
{
    auto hand_pose = std::make_unique<core::HandPoseT>();

    // Create and set joints.
    hand_pose->joints = std::make_unique<core::HandJoints>();

    CHECK(hand_pose->joints->poses()->size() == 26);
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

    // Mutate first joint
    hand_pose->joints->mutable_poses()->Mutate(0, joint_pose);

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

    // Set a few joint poses
    core::Point position(1.5f, 2.5f, 3.5f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    core::HandJointPose joint_pose(pose, true, 0.02f);

    hand_pose->joints->mutable_poses()->Mutate(0, joint_pose);

    // Serialize.
    auto offset = core::HandPose::Pack(builder, hand_pose.get());
    builder.Finish(offset);

    // Deserialize.
    auto buffer = builder.GetBufferPointer();
    auto deserialized = flatbuffers::GetRoot<core::HandPose>(buffer);

    // Verify.
    CHECK(deserialized->joints()->poses()->size() == 26);

    const auto* first_joint = (*deserialized->joints()->poses())[0];
    CHECK(first_joint->pose().position().x() == Catch::Approx(1.5f));
    CHECK(first_joint->pose().position().y() == Catch::Approx(2.5f));
    CHECK(first_joint->pose().position().z() == Catch::Approx(3.5f));
    CHECK(first_joint->is_valid() == true);
    CHECK(first_joint->radius() == Catch::Approx(0.02f));
}

TEST_CASE("HandPoseT can be unpacked from buffer", "[hand][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(4096);

    // Create and serialize.
    auto original = std::make_unique<core::HandPoseT>();
    original->joints = std::make_unique<core::HandJoints>();

    // Set multiple joint poses
    for (size_t i = 0; i < 26; ++i)
    {
        core::Point position(static_cast<float>(i), static_cast<float>(i * 2), static_cast<float>(i * 3));
        core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
        core::Pose pose(position, orientation);
        core::HandJointPose joint_pose(pose, true, 0.01f + static_cast<float>(i) * 0.001f);
        original->joints->mutable_poses()->Mutate(i, joint_pose);
    }

    auto offset = core::HandPose::Pack(builder, original.get());
    builder.Finish(offset);

    // Unpack to HandPoseT.
    auto buffer = builder.GetBufferPointer();
    auto hand_pose_fb = flatbuffers::GetRoot<core::HandPose>(buffer);
    auto unpacked = std::make_unique<core::HandPoseT>();
    hand_pose_fb->UnPackTo(unpacked.get());

    // Check a few joints.
    const auto* joint_5 = (*unpacked->joints->poses())[5];
    CHECK(joint_5->pose().position().x() == Catch::Approx(5.0f));
    CHECK(joint_5->pose().position().y() == Catch::Approx(10.0f));
    CHECK(joint_5->pose().position().z() == Catch::Approx(15.0f));

    const auto* joint_25 = (*unpacked->joints->poses())[25];
    CHECK(joint_25->pose().position().x() == Catch::Approx(25.0f));
    CHECK(joint_25->pose().position().y() == Catch::Approx(50.0f));
    CHECK(joint_25->pose().position().z() == Catch::Approx(75.0f));
}

TEST_CASE("HandPoseT all 26 joints can be set and verified", "[hand][native]")
{
    auto hand_pose = std::make_unique<core::HandPoseT>();
    hand_pose->joints = std::make_unique<core::HandJoints>();

    // Set all 26 joints with unique positions.
    for (size_t i = 0; i < 26; ++i)
    {
        core::Point position(static_cast<float>(i), 0.0f, 0.0f);
        core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
        core::Pose pose(position, orientation);
        core::HandJointPose joint_pose(pose, true, 0.01f);
        hand_pose->joints->mutable_poses()->Mutate(i, joint_pose);
    }

    // Verify all joints.
    for (size_t i = 0; i < 26; ++i)
    {
        const auto* joint = (*hand_pose->joints->poses())[i];
        CHECK(joint->pose().position().x() == Catch::Approx(static_cast<float>(i)));
        CHECK(joint->is_valid() == true);
    }
}

// =============================================================================
// HandPoseRecord Tests (timestamp lives on the Record wrapper)
// =============================================================================
TEST_CASE("HandPoseRecord serialization with DeviceDataTimestamp", "[hand][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(4096);

    auto record = std::make_shared<core::HandPoseRecordT>();
    record->data = std::make_shared<core::HandPoseT>();
    record->data->joints = std::make_shared<core::HandJoints>();
    record->timestamp = std::make_shared<core::DeviceDataTimestamp>(1000000000LL, 2000000000LL, 3000000000LL);

    auto offset = core::HandPoseRecord::Pack(builder, record.get());
    builder.Finish(offset);

    auto deserialized = flatbuffers::GetRoot<core::HandPoseRecord>(builder.GetBufferPointer());

    CHECK(deserialized->timestamp()->available_time_local_common_clock() == 1000000000LL);
    CHECK(deserialized->timestamp()->sample_time_local_common_clock() == 2000000000LL);
    CHECK(deserialized->timestamp()->sample_time_raw_device_clock() == 3000000000LL);
    CHECK(deserialized->data()->joints()->poses()->size() == 26);
}

TEST_CASE("HandPoseRecord can be unpacked with DeviceDataTimestamp", "[hand][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(4096);

    auto original = std::make_shared<core::HandPoseRecordT>();
    original->data = std::make_shared<core::HandPoseT>();
    original->data->joints = std::make_shared<core::HandJoints>();
    original->timestamp = std::make_shared<core::DeviceDataTimestamp>(111LL, 222LL, 333LL);

    auto offset = core::HandPoseRecord::Pack(builder, original.get());
    builder.Finish(offset);

    auto fb = flatbuffers::GetRoot<core::HandPoseRecord>(builder.GetBufferPointer());
    auto unpacked = std::make_shared<core::HandPoseRecordT>();
    fb->UnPackTo(unpacked.get());

    CHECK(unpacked->timestamp->available_time_local_common_clock() == 111LL);
    CHECK(unpacked->timestamp->sample_time_local_common_clock() == 222LL);
    CHECK(unpacked->timestamp->sample_time_raw_device_clock() == 333LL);
    CHECK(unpacked->data->joints->poses()->size() == 26);
}
