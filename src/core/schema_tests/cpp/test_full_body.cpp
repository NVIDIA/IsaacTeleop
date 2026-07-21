// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated FullBodyPose FlatBuffer message.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/full_body_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>
#include <type_traits>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs.
// These ensure schema field IDs remain stable across changes.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2
static_assert(core::FullBodyPose::VT_JOINTS == VT(0));

static_assert(core::FullBodyPoseRecord::VT_DATA == VT(0));

// =============================================================================
// Compile-time verification of FlatBuffer field types.
// These ensure schema field types remain stable across changes.
// =============================================================================
#define TYPE(field) decltype(std::declval<core::FullBodyPose>().field())
static_assert(std::is_same_v<TYPE(joints), const core::BodyJoints*>);

// =============================================================================
// Compile-time verification of BodyJointPose struct.
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::BodyJointPose>, "BodyJointPose should be a trivially copyable struct");

// =============================================================================
// Compile-time verification of BodyJoints struct.
// =============================================================================
static_assert(std::is_trivially_copyable_v<core::BodyJoints>, "BodyJoints should be a trivially copyable struct");

// BodyJoints should contain exactly 24 BodyJointPose entries.
static_assert(sizeof(core::BodyJoints) == 24 * sizeof(core::BodyJointPose),
              "BodyJoints should contain exactly 24 BodyJointPose entries");

// =============================================================================
// Compile-time verification of the deprecated "...Pico" back-compat aliases.
//
// full_body_compat.hpp is an opt-in header: nothing else in-tree includes it and
// the generated header does not pull it in, so without this block a mistyped alias
// (e.g. BodyJointPico_HEAD mapped to BodyJoint_NECK) would compile and ship
// silently. Lock every alias to its renamed target here, mirroring the Python
// TestDeprecatedPicoAliases coverage. The references are intentionally to
// [[deprecated]] names, so suppress that diagnostic for this block only.
// =============================================================================
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic push
#pragma GCC diagnostic ignored "-Wdeprecated-declarations"
#endif
#include <schema/full_body_compat.hpp>

// Type aliases resolve to the renamed generated types.
static_assert(std::is_same_v<core::FullBodyPosePico, core::FullBodyPose>);
static_assert(std::is_same_v<core::FullBodyPosePicoT, core::FullBodyPoseT>);
static_assert(std::is_same_v<core::FullBodyPosePicoTracked, core::FullBodyPoseTracked>);
static_assert(std::is_same_v<core::FullBodyPosePicoTrackedT, core::FullBodyPoseTrackedT>);
static_assert(std::is_same_v<core::FullBodyPosePicoRecord, core::FullBodyPoseRecord>);
static_assert(std::is_same_v<core::FullBodyPosePicoRecordT, core::FullBodyPoseRecordT>);
static_assert(std::is_same_v<core::BodyJointsPico, core::BodyJoints>);
static_assert(std::is_same_v<core::BodyJointPico, core::BodyJoint>);

// Every enumerator alias keeps its renamed target's numeric value.
static_assert(core::BodyJointPico_PELVIS == core::BodyJoint_PELVIS);
static_assert(core::BodyJointPico_LEFT_HIP == core::BodyJoint_LEFT_HIP);
static_assert(core::BodyJointPico_RIGHT_HIP == core::BodyJoint_RIGHT_HIP);
static_assert(core::BodyJointPico_SPINE1 == core::BodyJoint_SPINE1);
static_assert(core::BodyJointPico_LEFT_KNEE == core::BodyJoint_LEFT_KNEE);
static_assert(core::BodyJointPico_RIGHT_KNEE == core::BodyJoint_RIGHT_KNEE);
static_assert(core::BodyJointPico_SPINE2 == core::BodyJoint_SPINE2);
static_assert(core::BodyJointPico_LEFT_ANKLE == core::BodyJoint_LEFT_ANKLE);
static_assert(core::BodyJointPico_RIGHT_ANKLE == core::BodyJoint_RIGHT_ANKLE);
static_assert(core::BodyJointPico_SPINE3 == core::BodyJoint_SPINE3);
static_assert(core::BodyJointPico_LEFT_FOOT == core::BodyJoint_LEFT_FOOT);
static_assert(core::BodyJointPico_RIGHT_FOOT == core::BodyJoint_RIGHT_FOOT);
static_assert(core::BodyJointPico_NECK == core::BodyJoint_NECK);
static_assert(core::BodyJointPico_LEFT_COLLAR == core::BodyJoint_LEFT_COLLAR);
static_assert(core::BodyJointPico_RIGHT_COLLAR == core::BodyJoint_RIGHT_COLLAR);
static_assert(core::BodyJointPico_HEAD == core::BodyJoint_HEAD);
static_assert(core::BodyJointPico_LEFT_SHOULDER == core::BodyJoint_LEFT_SHOULDER);
static_assert(core::BodyJointPico_RIGHT_SHOULDER == core::BodyJoint_RIGHT_SHOULDER);
static_assert(core::BodyJointPico_LEFT_ELBOW == core::BodyJoint_LEFT_ELBOW);
static_assert(core::BodyJointPico_RIGHT_ELBOW == core::BodyJoint_RIGHT_ELBOW);
static_assert(core::BodyJointPico_LEFT_WRIST == core::BodyJoint_LEFT_WRIST);
static_assert(core::BodyJointPico_RIGHT_WRIST == core::BodyJoint_RIGHT_WRIST);
static_assert(core::BodyJointPico_LEFT_HAND == core::BodyJoint_LEFT_HAND);
static_assert(core::BodyJointPico_RIGHT_HAND == core::BodyJoint_RIGHT_HAND);
static_assert(core::BodyJointPico_NUM_JOINTS == core::BodyJoint_NUM_JOINTS);
#if defined(__GNUC__) || defined(__clang__)
#pragma GCC diagnostic pop
#endif

// =============================================================================
// Compile-time verification of BodyJoint enum.
// =============================================================================
static_assert(core::BodyJoint_PELVIS == 0, "PELVIS should be index 0");
static_assert(core::BodyJoint_RIGHT_HAND == 23, "RIGHT_HAND should be index 23");
static_assert(core::BodyJoint_NUM_JOINTS == 24, "NUM_JOINTS should be 24");

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
// BodyJoints Tests
// =============================================================================
TEST_CASE("BodyJoints struct has correct size", "[full_body][struct]")
{
    // BodyJoints should have exactly NUM_JOINTS entries (XR_BD_body_tracking).
    core::BodyJoints joints;
    CHECK(joints.joints()->size() == static_cast<size_t>(core::BodyJoint_NUM_JOINTS));
}

TEST_CASE("BodyJoints can be accessed by index", "[full_body][struct]")
{
    core::BodyJoints joints;

    // Access first and last entries (returns pointers).
    const auto* first = (*joints.joints())[0];
    const auto* last = (*joints.joints())[core::BodyJoint_NUM_JOINTS - 1];

    // Default values should be zero.
    CHECK(first->pose().position().x() == 0.0f);
    CHECK(last->pose().position().x() == 0.0f);
}

// =============================================================================
// FullBodyPoseT Tests
// =============================================================================
TEST_CASE("FullBodyPoseT default construction", "[full_body][native]")
{
    auto body_pose = std::make_unique<core::FullBodyPoseT>();

    // Default values.
    CHECK(body_pose->joints == nullptr);
}

TEST_CASE("FullBodyPoseT can store joints data", "[full_body][native]")
{
    auto body_pose = std::make_unique<core::FullBodyPoseT>();

    // Create and set joints.
    body_pose->joints = std::make_unique<core::BodyJoints>();

    CHECK(body_pose->joints->joints()->size() == static_cast<size_t>(core::BodyJoint_NUM_JOINTS));
}

TEST_CASE("FullBodyPoseT joints can be mutated via flatbuffers Array", "[full_body][native]")
{
    auto body_pose = std::make_unique<core::FullBodyPoseT>();
    body_pose->joints = std::make_unique<core::BodyJoints>();

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

TEST_CASE("FullBodyPoseT serialization and deserialization", "[full_body][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(4096);

    // Create FullBodyPoseT with all fields set.
    auto body_pose = std::make_unique<core::FullBodyPoseT>();
    body_pose->joints = std::make_unique<core::BodyJoints>();

    // Set a few joint poses
    core::Point position(1.5f, 2.5f, 3.5f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose pose(position, orientation);
    core::BodyJointPose joint_pose(pose, true);

    body_pose->joints->mutable_joints()->Mutate(0, joint_pose);

    // Serialize.
    auto offset = core::FullBodyPose::Pack(builder, body_pose.get());
    builder.Finish(offset);

    // Deserialize.
    auto buffer = builder.GetBufferPointer();
    auto deserialized = flatbuffers::GetRoot<core::FullBodyPose>(buffer);

    // Verify.
    CHECK(deserialized->joints()->joints()->size() == static_cast<size_t>(core::BodyJoint_NUM_JOINTS));

    const auto* first_joint = (*deserialized->joints()->joints())[0];
    CHECK(first_joint->pose().position().x() == Catch::Approx(1.5f));
    CHECK(first_joint->pose().position().y() == Catch::Approx(2.5f));
    CHECK(first_joint->pose().position().z() == Catch::Approx(3.5f));
    CHECK(first_joint->is_valid() == true);
}

TEST_CASE("FullBodyPoseT can be unpacked from buffer", "[full_body][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(4096);

    // Create and serialize.
    auto original = std::make_unique<core::FullBodyPoseT>();
    original->joints = std::make_unique<core::BodyJoints>();

    // Set multiple joint poses (--gen-mutable provides mutable_joints()).
    for (size_t i = 0; i < 24; ++i)
    {
        core::Point position(static_cast<float>(i), static_cast<float>(i * 2), static_cast<float>(i * 3));
        core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
        core::Pose pose(position, orientation);
        core::BodyJointPose joint_pose(pose, true);
        original->joints->mutable_joints()->Mutate(i, joint_pose);
    }

    auto offset = core::FullBodyPose::Pack(builder, original.get());
    builder.Finish(offset);

    // Unpack to FullBodyPoseT.
    auto buffer = builder.GetBufferPointer();
    auto body_pose_fb = flatbuffers::GetRoot<core::FullBodyPose>(buffer);
    auto unpacked = std::make_unique<core::FullBodyPoseT>();
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
}

TEST_CASE("FullBodyPoseT all 24 joints can be set and verified", "[full_body][native]")
{
    auto body_pose = std::make_unique<core::FullBodyPoseT>();
    body_pose->joints = std::make_unique<core::BodyJoints>();

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
TEST_CASE("FullBodyPoseT joint indices correspond to body parts", "[full_body][joints]")
{
    // This test documents the expected joint mapping from XR_BD_body_tracking.
    // Joint indices:
    //   0: Pelvis, 1-2: Left/Right Hip, 3: Spine1, 4-5: Left/Right Knee,
    //   6: Spine2, 7-8: Left/Right Ankle, 9: Spine3, 10-11: Left/Right Foot,
    //   12: Neck, 13-14: Left/Right Collar, 15: Head, 16-17: Left/Right Shoulder,
    //   18-19: Left/Right Elbow, 20-21: Left/Right Wrist, 22-23: Left/Right Hand

    auto body_pose = std::make_unique<core::FullBodyPoseT>();
    body_pose->joints = std::make_unique<core::BodyJoints>();

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
TEST_CASE("FullBodyPoseT buffer size is reasonable", "[full_body][serialize]")
{
    flatbuffers::FlatBufferBuilder builder;

    auto body_pose = std::make_unique<core::FullBodyPoseT>();
    body_pose->joints = std::make_unique<core::BodyJoints>();

    auto offset = core::FullBodyPose::Pack(builder, body_pose.get());
    builder.Finish(offset);

    // Buffer should be reasonably sized for 24 joints.
    // Each BodyJointPose is Pose (28 bytes) + bool (1 byte with padding) = ~32 bytes.
    // 24 joints * 32 bytes = ~768 bytes, plus overhead.
    CHECK(builder.GetSize() < 2000);
}

// =============================================================================
// BodyJoint Enum Tests
// =============================================================================
TEST_CASE("BodyJoint enum has correct values", "[full_body][enum]")
{
    // Verify all 24 enum values match the XR_BD_body_tracking joint indices.
    CHECK(core::BodyJoint_PELVIS == 0);
    CHECK(core::BodyJoint_LEFT_HIP == 1);
    CHECK(core::BodyJoint_RIGHT_HIP == 2);
    CHECK(core::BodyJoint_SPINE1 == 3);
    CHECK(core::BodyJoint_LEFT_KNEE == 4);
    CHECK(core::BodyJoint_RIGHT_KNEE == 5);
    CHECK(core::BodyJoint_SPINE2 == 6);
    CHECK(core::BodyJoint_LEFT_ANKLE == 7);
    CHECK(core::BodyJoint_RIGHT_ANKLE == 8);
    CHECK(core::BodyJoint_SPINE3 == 9);
    CHECK(core::BodyJoint_LEFT_FOOT == 10);
    CHECK(core::BodyJoint_RIGHT_FOOT == 11);
    CHECK(core::BodyJoint_NECK == 12);
    CHECK(core::BodyJoint_LEFT_COLLAR == 13);
    CHECK(core::BodyJoint_RIGHT_COLLAR == 14);
    CHECK(core::BodyJoint_HEAD == 15);
    CHECK(core::BodyJoint_LEFT_SHOULDER == 16);
    CHECK(core::BodyJoint_RIGHT_SHOULDER == 17);
    CHECK(core::BodyJoint_LEFT_ELBOW == 18);
    CHECK(core::BodyJoint_RIGHT_ELBOW == 19);
    CHECK(core::BodyJoint_LEFT_WRIST == 20);
    CHECK(core::BodyJoint_RIGHT_WRIST == 21);
    CHECK(core::BodyJoint_LEFT_HAND == 22);
    CHECK(core::BodyJoint_RIGHT_HAND == 23);
    CHECK(core::BodyJoint_NUM_JOINTS == 24);
}

TEST_CASE("BodyJoint enum can index BodyJoints", "[full_body][enum]")
{
    auto body_pose = std::make_unique<core::FullBodyPoseT>();
    body_pose->joints = std::make_unique<core::BodyJoints>();

    // Set specific joints using enum values (--gen-mutable provides mutable_joints()).
    // Set HEAD joint with a recognizable position.
    core::Point head_position(0.0f, 1.7f, 0.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    core::Pose head_pose(head_position, orientation);
    core::BodyJointPose head_joint(head_pose, true);
    body_pose->joints->mutable_joints()->Mutate(core::BodyJoint_HEAD, head_joint);

    // Set LEFT_HAND joint with a recognizable position.
    core::Point left_hand_position(-0.5f, 1.0f, 0.3f);
    core::Pose left_hand_pose(left_hand_position, orientation);
    core::BodyJointPose left_hand_joint(left_hand_pose, true);
    body_pose->joints->mutable_joints()->Mutate(core::BodyJoint_LEFT_HAND, left_hand_joint);

    // Verify using enum values to access.
    const auto* head = (*body_pose->joints->joints())[core::BodyJoint_HEAD];
    CHECK(head->pose().position().y() == Catch::Approx(1.7f));
    CHECK(head->is_valid() == true);

    const auto* left_hand = (*body_pose->joints->joints())[core::BodyJoint_LEFT_HAND];
    CHECK(left_hand->pose().position().x() == Catch::Approx(-0.5f));
    CHECK(left_hand->is_valid() == true);
}

// =============================================================================
// FullBodyPoseRecord Tests (timestamp lives on the Record wrapper)
// =============================================================================
TEST_CASE("FullBodyPoseRecord serialization with DeviceDataTimestamp", "[full_body][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(4096);

    auto record = std::make_shared<core::FullBodyPoseRecordT>();
    record->data = std::make_shared<core::FullBodyPoseT>();
    record->data->joints = std::make_unique<core::BodyJoints>();
    record->timestamp = std::make_shared<core::DeviceDataTimestamp>(1000000000LL, 2000000000LL, 3000000000LL);

    auto offset = core::FullBodyPoseRecord::Pack(builder, record.get());
    builder.Finish(offset);

    auto deserialized = flatbuffers::GetRoot<core::FullBodyPoseRecord>(builder.GetBufferPointer());

    CHECK(deserialized->timestamp()->available_time_local_common_clock() == 1000000000LL);
    CHECK(deserialized->timestamp()->sample_time_local_common_clock() == 2000000000LL);
    CHECK(deserialized->timestamp()->sample_time_raw_device_clock() == 3000000000LL);
    CHECK(deserialized->data()->joints()->joints()->size() == static_cast<size_t>(core::BodyJoint_NUM_JOINTS));
}

TEST_CASE("FullBodyPoseRecord can be unpacked with DeviceDataTimestamp", "[full_body][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(4096);

    auto original = std::make_shared<core::FullBodyPoseRecordT>();
    original->data = std::make_shared<core::FullBodyPoseT>();
    original->data->joints = std::make_unique<core::BodyJoints>();
    original->timestamp = std::make_shared<core::DeviceDataTimestamp>(111LL, 222LL, 333LL);

    auto offset = core::FullBodyPoseRecord::Pack(builder, original.get());
    builder.Finish(offset);

    auto fb = flatbuffers::GetRoot<core::FullBodyPoseRecord>(builder.GetBufferPointer());
    auto unpacked = std::make_shared<core::FullBodyPoseRecordT>();
    fb->UnPackTo(unpacked.get());

    CHECK(unpacked->timestamp->available_time_local_common_clock() == 111LL);
    CHECK(unpacked->timestamp->sample_time_local_common_clock() == 222LL);
    CHECK(unpacked->timestamp->sample_time_raw_device_clock() == 333LL);
    CHECK(unpacked->data->joints->joints()->size() == static_cast<size_t>(core::BodyJoint_NUM_JOINTS));
}
