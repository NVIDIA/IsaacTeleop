// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated HeadPose FlatBuffer message.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/head_generated.h>

#include <type_traits>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs.
// These ensure schema field IDs remain stable across changes.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2
static_assert(core::HeadPose::VT_POSE == VT(0));
static_assert(core::HeadPose::VT_IS_VALID == VT(1));
static_assert(core::HeadPose::VT_TIMESTAMP == VT(2));

static_assert(core::HeadPoseRecord::VT_DATA == VT(0));

// =============================================================================
// Compile-time verification of FlatBuffer field types.
// These ensure schema field types remain stable across changes.
// =============================================================================
#define TYPE(field) decltype(std::declval<core::HeadPose>().field())
static_assert(std::is_same_v<TYPE(pose), const core::Pose*>);
static_assert(std::is_same_v<TYPE(is_valid), bool>);
static_assert(std::is_same_v<TYPE(timestamp), const core::Timestamp*>);


TEST_CASE("HeadPoseT can handle is_valid value properly", "[head][native]")
{
    flatbuffers::FlatBufferBuilder builder(1024);

    // Create HeadPoseT with default values, is_valid should be false.
    auto head_pose = std::make_unique<core::HeadPoseT>();
    CHECK(head_pose->is_valid == false);

    // Set is_valid to true.
    head_pose->is_valid = true;
    CHECK(head_pose->is_valid == true);
}

TEST_CASE("HeadPoseT default construction", "[head][native]")
{
    auto head_pose = std::make_unique<core::HeadPoseT>();

    // Default values.
    CHECK(head_pose->pose == nullptr);
    CHECK(head_pose->is_valid == false);
    CHECK(head_pose->timestamp == nullptr);
}

TEST_CASE("HeadPoseT can store pose data", "[head][native]")
{
    auto head_pose = std::make_unique<core::HeadPoseT>();

    // Create and set pose.
    core::Point position(1.5f, 2.5f, 3.5f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f); // Identity quaternion.
    head_pose->pose = std::make_unique<core::Pose>(position, orientation);

    // Verify pose data.
    REQUIRE(head_pose->pose != nullptr);
    CHECK(head_pose->pose->position().x() == Catch::Approx(1.5f));
    CHECK(head_pose->pose->position().y() == Catch::Approx(2.5f));
    CHECK(head_pose->pose->position().z() == Catch::Approx(3.5f));
    CHECK(head_pose->pose->orientation().x() == Catch::Approx(0.0f));
    CHECK(head_pose->pose->orientation().y() == Catch::Approx(0.0f));
    CHECK(head_pose->pose->orientation().z() == Catch::Approx(0.0f));
    CHECK(head_pose->pose->orientation().w() == Catch::Approx(1.0f));
}

TEST_CASE("HeadPoseT can store timestamp", "[head][native]")
{
    auto head_pose = std::make_unique<core::HeadPoseT>();

    // Set timestamp (XrTime is int64_t).
    int64_t test_device_time = 1234567890123456789LL;
    int64_t test_common_time = 9876543210LL;
    head_pose->timestamp = std::make_shared<core::Timestamp>(test_device_time, test_common_time);

    REQUIRE(head_pose->timestamp != nullptr);
    CHECK(head_pose->timestamp->device_time() == test_device_time);
    CHECK(head_pose->timestamp->common_time() == test_common_time);
}

TEST_CASE("HeadPoseT can store rotation quaternion", "[head][native]")
{
    auto head_pose = std::make_unique<core::HeadPoseT>();

    // 90-degree rotation around Z axis.
    core::Point position(0.0f, 0.0f, 0.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.7071068f, 0.7071068f); // (x, y, z, w)
    head_pose->pose = std::make_unique<core::Pose>(position, orientation);

    REQUIRE(head_pose->pose != nullptr);
    CHECK(head_pose->pose->orientation().z() == Catch::Approx(0.7071068f).epsilon(0.0001));
    CHECK(head_pose->pose->orientation().w() == Catch::Approx(0.7071068f).epsilon(0.0001));
}

TEST_CASE("HeadPoseT serialization and deserialization", "[head][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(1024);

    // Create HeadPoseT with all fields set.
    auto head_pose = std::make_unique<core::HeadPoseT>();
    core::Point position(1.0f, 2.0f, 3.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    head_pose->pose = std::make_unique<core::Pose>(position, orientation);
    head_pose->is_valid = true;
    head_pose->timestamp = std::make_shared<core::Timestamp>(9876543210LL, 1234567890LL);

    // Serialize.
    auto offset = core::HeadPose::Pack(builder, head_pose.get());
    builder.Finish(offset);

    // Deserialize.
    auto buffer = builder.GetBufferPointer();
    auto deserialized = flatbuffers::GetRoot<core::HeadPose>(buffer);

    // Verify.
    REQUIRE(deserialized->pose() != nullptr);
    CHECK(deserialized->pose()->position().x() == Catch::Approx(1.0f));
    CHECK(deserialized->pose()->position().y() == Catch::Approx(2.0f));
    CHECK(deserialized->pose()->position().z() == Catch::Approx(3.0f));
    CHECK(deserialized->is_valid() == true);
    REQUIRE(deserialized->timestamp() != nullptr);
    CHECK(deserialized->timestamp()->device_time() == 9876543210LL);
    CHECK(deserialized->timestamp()->common_time() == 1234567890LL);
}

TEST_CASE("HeadPoseT can be unpacked from buffer", "[head][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(1024);

    // Create and serialize.
    auto original = std::make_unique<core::HeadPoseT>();
    core::Point position(5.0f, 6.0f, 7.0f);
    core::Quaternion orientation(0.1f, 0.2f, 0.3f, 0.9f);
    original->pose = std::make_unique<core::Pose>(position, orientation);
    original->is_valid = true;
    original->timestamp = std::make_shared<core::Timestamp>(1111111111LL, 2222222222LL);

    auto offset = core::HeadPose::Pack(builder, original.get());
    builder.Finish(offset);

    // Unpack to HeadPoseT.
    auto buffer = builder.GetBufferPointer();
    auto head_pose_fb = flatbuffers::GetRoot<core::HeadPose>(buffer);
    auto unpacked = std::make_unique<core::HeadPoseT>();
    head_pose_fb->UnPackTo(unpacked.get());

    // Verify unpacked data.
    REQUIRE(unpacked->pose != nullptr);
    CHECK(unpacked->pose->position().x() == Catch::Approx(5.0f));
    CHECK(unpacked->pose->position().y() == Catch::Approx(6.0f));
    CHECK(unpacked->pose->position().z() == Catch::Approx(7.0f));
    CHECK(unpacked->is_valid == true);
    REQUIRE(unpacked->timestamp != nullptr);
    CHECK(unpacked->timestamp->device_time() == 1111111111LL);
    CHECK(unpacked->timestamp->common_time() == 2222222222LL);
}
