// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated FullBodyPosePico FlatBuffer message.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/full_body_generated.h>

#include <memory>
#include <type_traits>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs.
// These ensure schema field IDs remain stable across changes.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2
static_assert(core::FullBodyPosePico::VT_TIMESTAMP == VT(0));
static_assert(core::FullBodyPosePico::VT_JOINTS == VT(1));

static_assert(core::FullBodyPosePicoRecord::VT_DATA == VT(0));

// =============================================================================
// Compile-time verification of FlatBuffer field types.
// These ensure schema field types remain stable across changes.
// =============================================================================
#define TYPE(field) decltype(std::declval<core::FullBodyPosePico>().field())
static_assert(std::is_same_v<TYPE(joints), const core::BodyJointsPico*>);
static_assert(std::is_same_v<TYPE(timestamp), const core::Timestamp*>);

// =============================================================================
// Compile-time verification of BodyJointPose struct.
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::BodyJointPose>, "BodyJointPose should be a trivially copyable struct");

// =============================================================================
// Compile-time verification of BodyJointsPico struct.
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::BodyJointsPico>, "BodyJointsPico should be a trivially copyable struct");

// BodyJointsPico should contain exactly 24 BodyJointPose entries.
static_assert(sizeof(core::BodyJointsPico) == 24 * sizeof(core::BodyJointPose),
              "BodyJointsPico should contain exactly 24 BodyJointPose entries");

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
// BodyJointsPico Tests
// =============================================================================
TEST_CASE("BodyJointsPico struct has correct size", "[full_body][struct]")
{
    // BodyJointsPico should have exactly NUM_JOINTS entries (XR_BD_body_tracking).
    core::BodyJointsPico joints;
    CHECK(joints.joints()->size() == static_cast<size_t>(core::BodyJointPico_NUM_JOINTS));
}

TEST_CASE("BodyJointsPico can be accessed by index", "[full_body][struct]")
{
    core::BodyJointsPico joints;

    // Access first and last entries (returns pointers).
    const auto* first = (*joints.joints())[0];
    const auto* last = (*joints.joints())[core::BodyJointPico_NUM_JOINTS - 1];

    // Default values should be zero.
    CHECK(first->pose().position().x() == 0.0f);
    CHECK(last->pose().position().x() == 0.0f);
}

// =============================================================================
// FullBodyPosePicoT Tests
// =============================================================================
TEST_CASE("FullBodyPosePicoT default construction", "[full_body][native]")
{
    auto body_pose = std::make_unique<core::FullBodyPosePicoT>();

    // Default values.
    CHECK(body_pose->joints == nullptr);
    CHECK(body_pose->timestamp == nullptr);
}

TEST_CASE("FullBodyPosePicoT can store joints data", "[full_body][native]")
{
    auto body_pose = std::make_unique<core::FullBodyPosePicoT>();

    // Create and set joints.
    body_pose->joints = std::make_unique<core::BodyJointsPico>();

    CHECK(body_pose->joints->joints()->size() == static_cast<size_t>(core::BodyJointPico_NUM_JOINTS));
}

TEST_CASE("FullBodyPosePicoT can store timestamp", "[full_body][native]")
{
    auto body_pose = std::make_unique<core::FullBodyPosePicoT>();

    // Set timestamp (XrTime is int64_t).
    int64_t test_device_time = 1234567890123456789LL;
    int64_t test_common_time = 9876543210LL;
    body_pose->timestamp = std::make_shared<core::Timestamp>(test_device_time, test_common_time);

    CHECK(body_pose->timestamp->device_time() == test_device_time);
    CHECK(body_pose->timestamp->common_time() == test_common_time);
}

TEST_CASE("FullBodyPosePicoT joints can be mutated via flatbuffers Array", "[full_body][native]")
{
    auto body_pose = std::make_unique<core::FullBodyPosePicoT>();
    body_pose->joints = std::make_unique<core::BodyJointsPico>();

    // Create a joint pose.
    core::Point position(1.0f, 2.0f, 3.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    core::BodyJointPose joint_pose(pose, true);

    // Mutate first joint
    body_pose->joints->mutable_joints()->Mutate(0, joint_pose);

    // Verify.
    const auto* first_joint = (*body_pose->joints->joints())[0];
    CHECK(first_joint->pose().position().x() == 1.0f);
    CHECK(first_joint->pose().position().y() == 2.0f);
    CHECK(first_joint->pose().position().z() == 3.0f);
    CHECK(first_joint->is_valid() == true);
}

TEST_CASE("FullBodyPosePicoT serialization and deserialization", "[full_body][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(4096);

    // Create FullBodyPosePicoT with all fields set.
    auto body_pose = std::make_unique<core::FullBodyPosePicoT>();
    body_pose->joints = std::make_unique<core::BodyJointsPico>();

    // Set a few joint poses
    core::Point position(1.5f, 2.5f, 3.5f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    core::BodyJointPose joint_pose(pose, true);

    body_pose->joints->mutable_joints()->Mutate(0, joint_pose);

    body_pose->timestamp = std::make_shared<core::Timestamp>(9876543210LL, 1234567890LL);

    // Serialize.
    auto offset = core::FullBodyPosePico::Pack(builder, body_pose.get());
    builder.Finish(offset);

    // Deserialize.
    auto buffer = builder.GetBufferPointer();
    auto deserialized = flatbuffers::GetRoot<core::FullBodyPosePico>(buffer);

    // Verify.
    CHECK(deserialized->joints()->joints()->size() == static_cast<size_t>(core::BodyJointPico_NUM_JOINTS));

    const auto* first_joint = (*deserialized->joints()->joints())[0];
    CHECK(first_joint->pose().position().x() == Catch::Approx(1.5f));
    CHECK(first_joint->pose().position().y() == Catch::Approx(2.5f));
    CHECK(first_joint->pose().position().z() == Catch::Approx(3.5f));
    CHECK(first_joint->is_valid() == true);

    CHECK(deserialized->timestamp()->device_time() == 9876543210LL);
    CHECK(deserialized->timestamp()->common_time() == 1234567890LL);
}

TEST_CASE("FullBodyPosePicoT can be unpacked from buffer", "[full_body][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(4096);

    // Create and serialize.
    auto original = std::make_unique<core::FullBodyPosePicoT>();
    original->joints = std::make_unique<core::BodyJointsPico>();

    // Set multiple joint poses (--gen-mutable provides mutable_joints()).
    for (size_t i = 0; i < 24; ++i)
    {
        core::Point position(static_cast<float>(i), static_cast<float>(i * 2), static_cast<float>(i * 3));
        core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
        core::Pose pose(position, orientation);
        core::BodyJointPose joint_pose(pose, true);
        original->joints->mutable_joints()->Mutate(i, joint_pose);
    }

    original->timestamp = std::make_shared<core::Timestamp>(1111111111LL, 2222222222LL);

    auto offset = core::FullBodyPosePico::Pack(builder, original.get());
    builder.Finish(offset);

    // Unpack to FullBodyPosePicoT.
    auto buffer = builder.GetBufferPointer();
    auto body_pose_fb = flatbuffers::GetRoot<core::FullBodyPosePico>(buffer);
    auto unpacked = std::make_unique<core::FullBodyPosePicoT>();
    body_pose_fb->UnPackTo(unpacked.get());

    // Check a few joints.
    const auto* joint_5 = (*unpacked->joints->joints())[5];
    CHECK(joint_5->pose().position().x() == Catch::Approx(5.0f));
    CHECK(joint_5->pose().position().y() == Catch::Approx(10.0f));
    CHECK(joint_5->pose().position().z() == Catch::Approx(15.0f));

    const auto* joint_23 = (*unpacked->joints->joints())[23];
    CHECK(joint_23->pose().position().x() == Catch::Approx(23.0f));
    CHECK(joint_23->pose().position().y() == Catch::Approx(46.0f));
    CHECK(joint_23->pose().position().z() == Catch::Approx(69.0f));

    CHECK(unpacked->timestamp->device_time() == 1111111111LL);
    CHECK(unpacked->timestamp->common_time() == 2222222222LL);
}

TEST_CASE("FullBodyPosePicoT all 24 joints can be set and verified", "[full_body][native]")
{
    auto body_pose = std::make_unique<core::FullBodyPosePicoT>();
    body_pose->joints = std::make_unique<core::BodyJointsPico>();

    // Set all 24 joints with unique positions (--gen-mutable provides mutable_joints()).
    for (size_t i = 0; i < 24; ++i)
    {
        core::Point position(static_cast<float>(i), 0.0f, 0.0f);
        core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
        core::Pose pose(position, orientation);
        core::BodyJointPose joint_pose(pose, true);
        body_pose->joints->mutable_joints()->Mutate(i, joint_pose);
    }

    // Verify all joints.
    for (size_t i = 0; i < 24; ++i)
    {
        const auto* joint = (*body_pose->joints->joints())[i];
        CHECK(joint->pose().position().x() == Catch::Approx(static_cast<float>(i)));
        CHECK(joint->is_valid() == true);
    }
}

// =============================================================================
// Body Joint Index Tests (XR_BD_body_tracking joint mapping)
// =============================================================================
TEST_CASE("FullBodyPosePicoT joint indices correspond to body parts", "[full_body][joints]")
{
    // This test documents the expected joint mapping from XR_BD_body_tracking.
    // Joint indices:
    //   0: Pelvis, 1-2: Left/Right Hip, 3: Spine1, 4-5: Left/Right Knee,
    //   6: Spine2, 7-8: Left/Right Ankle, 9: Spine3, 10-11: Left/Right Foot,
    //   12: Neck, 13-14: Left/Right Collar, 15: Head, 16-17: Left/Right Shoulder,
    //   18-19: Left/Right Elbow, 20-21: Left/Right Wrist, 22-23: Left/Right Hand

    auto body_pose = std::make_unique<core::FullBodyPosePicoT>();
    body_pose->joints = std::make_unique<core::BodyJointsPico>();

    // Verify we can access all expected joint indices.
    REQUIRE(body_pose->joints->joints()->size() == 24);

    // Access key joints by index.
    const auto* pelvis = (*body_pose->joints->joints())[0];
    const auto* head = (*body_pose->joints->joints())[15];
    const auto* left_hand = (*body_pose->joints->joints())[22];
    const auto* right_hand = (*body_pose->joints->joints())[23];

    CHECK(pelvis->pose().position().x() == 0.0f);
    CHECK(head->pose().position().x() == 0.0f);
    CHECK(left_hand->pose().position().x() == 0.0f);
    CHECK(right_hand->pose().position().x() == 0.0f);
}

// =============================================================================
// Edge Cases
// =============================================================================
TEST_CASE("FullBodyPosePicoT with large timestamp values", "[full_body][edge]")
{
    auto body_pose = std::make_unique<core::FullBodyPosePicoT>();
    int64_t max_int64 = 9223372036854775807LL;
    body_pose->timestamp = std::make_shared<core::Timestamp>(max_int64, max_int64 - 1000);

    CHECK(body_pose->timestamp->device_time() == max_int64);
    CHECK(body_pose->timestamp->common_time() == max_int64 - 1000);
}

TEST_CASE("FullBodyPosePicoT buffer size is reasonable", "[full_body][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    auto body_pose = std::make_unique<core::FullBodyPosePicoT>();
    body_pose->joints = std::make_unique<core::BodyJointsPico>();
    body_pose->timestamp = std::make_shared<core::Timestamp>(0, 0);

    auto offset = core::FullBodyPosePico::Pack(builder, body_pose.get());
    builder.Finish(offset);

    // Buffer should be reasonably sized for 24 joints.
    // Each BodyJointPose is Pose (28 bytes) + bool (1 byte with padding) = ~32 bytes.
    // 24 joints * 32 bytes = ~768 bytes, plus overhead.
    CHECK(builder.GetSize() < 2000);
}

// =============================================================================
// BodyJointPico Enum Tests
// =============================================================================
TEST_CASE("BodyJointPico enum has correct values", "[full_body][enum]")
{
    // Verify all 24 enum values match the XR_BD_body_tracking joint indices.
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

TEST_CASE("BodyJointPico enum can index BodyJointsPico", "[full_body][enum]")
{
    auto body_pose = std::make_unique<core::FullBodyPosePicoT>();
    body_pose->joints = std::make_unique<core::BodyJointsPico>();

    // Set specific joints using enum values (--gen-mutable provides mutable_joints()).
    // Set HEAD joint with a recognizable position.
    core::Point head_position(0.0f, 1.7f, 0.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose head_pose(head_position, orientation);
    core::BodyJointPose head_joint(head_pose, true);
    body_pose->joints->mutable_joints()->Mutate(core::BodyJointPico_HEAD, head_joint);

    // Set LEFT_HAND joint with a recognizable position.
    core::Point left_hand_position(-0.5f, 1.0f, 0.3f);
    core::Pose left_hand_pose(left_hand_position, orientation);
    core::BodyJointPose left_hand_joint(left_hand_pose, true);
    body_pose->joints->mutable_joints()->Mutate(core::BodyJointPico_LEFT_HAND, left_hand_joint);

    // Verify using enum values to access.
    const auto* head = (*body_pose->joints->joints())[core::BodyJointPico_HEAD];
    CHECK(head->pose().position().y() == Catch::Approx(1.7f));
    CHECK(head->is_valid() == true);

    const auto* left_hand = (*body_pose->joints->joints())[core::BodyJointPico_LEFT_HAND];
    CHECK(left_hand->pose().position().x() == Catch::Approx(-0.5f));
    CHECK(left_hand->is_valid() == true);
}
