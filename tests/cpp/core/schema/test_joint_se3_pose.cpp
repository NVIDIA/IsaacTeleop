// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated JointSe3PoseOutput FlatBuffer message.

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/joint_se3_pose_family.hpp>
#include <schema/joint_se3_pose_generated.h>
#include <schema/timestamp_generated.h>

#include <string>
#include <type_traits>
#include <vector>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs.
// These ensure schema field IDs remain stable across changes.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
#define VT(field) (field + 2) * 2
static_assert(core::JointSe3PoseOutput::VT_TYPE == VT(0));
static_assert(core::JointSe3PoseOutput::VT_JOINTS == VT(1));
static_assert(core::JointSe3PoseOutput::VT_DEVICE_ID == VT(2));

static_assert(core::JointSe3PoseOutputRecord::VT_DATA == VT(0));
static_assert(core::JointSe3PoseOutputRecord::VT_TIMESTAMP == VT(1));

// =============================================================================
// Compile-time verification of FlatBuffer field types.
// =============================================================================
static_assert(std::is_same_v<decltype(std::declval<core::JointSe3Pose>().joint()), core::JointName>);
static_assert(std::is_same_v<decltype(std::declval<core::JointSe3Pose>().pose()), const core::Pose&>);

// A struct is stored inline with no vtable, so its size is baked into every layout enclosing
// it. Resizing JointSe3Pose silently misreads every recorded vector of them.
static_assert(sizeof(core::JointSe3Pose) == 32);

namespace
{

// One tip at (index, 0, 0), so a joint's position identifies which entry it came from.
core::JointSe3Pose tip(core::JointName joint, float x)
{
    return core::JointSe3Pose(joint, core::Pose(core::Point(x, 0.0F, 0.0F), core::Quaternion(0.0F, 0.0F, 0.0F, 1.0F)));
}

} // namespace

TEST_CASE("JointSe3PoseOutput looks joints up by name", "[joint_se3_pose]")
{
    // Deliberately unsorted, and missing RING: the vector is sparse, and a producer must not
    // have to hand the builder its joints in order.
    std::vector<core::JointSe3Pose> joints{
        tip(core::JointName_HAND_RAW_LITTLE_TIP, 4.0F),
        tip(core::JointName_HAND_RAW_THUMB_TIP, 0.0F),
        tip(core::JointName_HAND_RAW_MIDDLE_TIP, 2.0F),
        tip(core::JointName_HAND_RAW_INDEX_TIP, 1.0F),
    };

    flatbuffers::FlatBufferBuilder builder(1024);
    const auto device_id = builder.CreateString("manus_sensors_left");
    const auto joints_offset = builder.CreateVectorOfSortedStructs(&joints);
    builder.Finish(core::CreateJointSe3PoseOutput(builder, core::JointType_HAND_RAW, joints_offset, device_id));

    const auto* out = flatbuffers::GetRoot<core::JointSe3PoseOutput>(builder.GetBufferPointer());
    REQUIRE(out->joints() != nullptr);
    REQUIRE(out->joints()->size() == 4);
    CHECK(out->device_id()->str() == "manus_sensors_left");
    CHECK(out->type() == core::JointType_HAND_RAW);

    SECTION("every written joint comes back, carrying its own pose")
    {
        // LookupByKey on an unsorted vector returns a neighbour rather than failing, so
        // checking the position -- not just non-null -- is what proves the sort happened.
        const std::vector<std::pair<core::JointName, float>> expected{
            { core::JointName_HAND_RAW_THUMB_TIP, 0.0F },
            { core::JointName_HAND_RAW_INDEX_TIP, 1.0F },
            { core::JointName_HAND_RAW_MIDDLE_TIP, 2.0F },
            { core::JointName_HAND_RAW_LITTLE_TIP, 4.0F },
        };
        for (const auto& [joint, x] : expected)
        {
            const auto* found = out->joints()->LookupByKey(joint);
            REQUIRE(found != nullptr);
            CHECK(found->joint() == joint);
            CHECK(found->pose().position().x() == x);
        }
    }

    SECTION("the vector is sorted ascending on the wire")
    {
        core::JointName previous = core::JointName_UNKNOWN;
        for (const auto* joint : *out->joints())
        {
            CHECK(joint->joint() > previous);
            previous = joint->joint();
        }
    }

    SECTION("an untracked joint misses rather than returning a neighbour")
    {
        // RING sits between MIDDLE and LITTLE, so a lookup that fell through to the nearest
        // entry would answer with one of those.
        CHECK(out->joints()->LookupByKey(core::JointName_HAND_RAW_RING_TIP) == nullptr);
        CHECK(out->joints()->LookupByKey(core::JointName_UNKNOWN) == nullptr);
    }
}

TEST_CASE("JointSe3PoseOutput carries no joints when the device reports none", "[joint_se3_pose]")
{
    flatbuffers::FlatBufferBuilder builder(1024);
    std::vector<core::JointSe3Pose> joints;
    const auto joints_offset = builder.CreateVectorOfSortedStructs(&joints);
    builder.Finish(
        core::CreateJointSe3PoseOutput(builder, core::JointType_HAND_RAW, joints_offset, builder.CreateString("")));

    const auto* out = flatbuffers::GetRoot<core::JointSe3PoseOutput>(builder.GetBufferPointer());
    REQUIRE(out->joints() != nullptr);
    CHECK(out->joints()->size() == 0);
    // The point of carrying type as a field: an all-untracked frame still names its family,
    // which no amount of inspecting the (empty) key vector could tell you.
    CHECK(out->type() == core::JointType_HAND_RAW);
    CHECK(out->joints()->LookupByKey(core::JointName_HAND_RAW_THUMB_TIP) == nullptr);
}

TEST_CASE("JointSe3PoseOutputT round-trips through the object API", "[joint_se3_pose][native]")
{
    core::JointSe3PoseOutputT native;
    native.type = core::JointType_HAND_RAW;
    native.device_id = "manus_sensors_right";
    native.joints = {
        tip(core::JointName_HAND_RAW_THUMB_TIP, 0.0F),
        tip(core::JointName_HAND_RAW_LITTLE_TIP, 4.0F),
    };

    flatbuffers::FlatBufferBuilder builder(1024);
    builder.Finish(core::JointSe3PoseOutput::Pack(builder, &native));

    const auto* out = flatbuffers::GetRoot<core::JointSe3PoseOutput>(builder.GetBufferPointer());
    CHECK(out->device_id()->str() == "manus_sensors_right");
    CHECK(out->type() == core::JointType_HAND_RAW);
    REQUIRE(out->joints()->size() == 2);
    // Pack() writes the vector in the order given (CreateVectorOfStructs, not the sorted
    // variant), so callers that build through it must sort first. This pins that behaviour:
    // if flatc ever starts sorting here, the writers that sort by hand need revisiting.
    CHECK((*out->joints())[0]->joint() == core::JointName_HAND_RAW_THUMB_TIP);
    CHECK((*out->joints())[1]->joint() == core::JointName_HAND_RAW_LITTLE_TIP);
}

TEST_CASE("JointName values fall in their JointType block", "[joint_se3_pose]")
{
    // The family of a joint is the greatest JointType not exceeding it. Block widths differ
    // (100 for hands, 1000 for bodies), so rounding to a fixed width is not the rule; this
    // pins the allocation the writers rely on when they stamp `type`.
    for (const auto joint :
         { core::JointName_HAND_RAW_THUMB_TIP, core::JointName_HAND_RAW_INDEX_TIP, core::JointName_HAND_RAW_MIDDLE_TIP,
           core::JointName_HAND_RAW_RING_TIP, core::JointName_HAND_RAW_LITTLE_TIP })
    {
        CHECK(static_cast<int>(joint) >= static_cast<int>(core::JointType_HAND_RAW));
        // Below the next allocated base, so these never read as HAND_OPENXR or a body family.
        CHECK(static_cast<int>(joint) < 1200);
        CHECK(static_cast<int>(joint) > static_cast<int>(core::JointType_HAND_OPENXR));
    }
    CHECK(static_cast<int>(core::JointType_UNKNOWN) == 0);
}

TEST_CASE("joint_family maps a joint onto its block base", "[joint_se3_pose]")
{
    CHECK(core::joint_family(core::JointName_HAND_RAW_THUMB_TIP) == core::JointType_HAND_RAW);
    CHECK(core::joint_family(core::JointName_HAND_RAW_LITTLE_TIP) == core::JointType_HAND_RAW);
    // Below every allocated base.
    CHECK(core::joint_family(core::JointName_UNKNOWN) == core::JointType_UNKNOWN);
    // A value inside the HAND_OPENXR block that has no enumerator yet still reads as that family:
    // the rule is the block it falls in, not the names allocated so far.
    CHECK(core::joint_family(static_cast<core::JointName>(1042)) == core::JointType_HAND_OPENXR);
}
