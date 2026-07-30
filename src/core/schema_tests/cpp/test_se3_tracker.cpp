// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated Se3TrackerPose FlatBuffer message.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/se3_tracker_generated.h>
#include <schema/timestamp_generated.h>

#include <memory>
#include <type_traits>

// =============================================================================
// Compile-time verification of FlatBuffer field IDs.
// These ensure schema field IDs remain stable across changes.
// VT values are computed as: (field_id + 2) * 2.
// =============================================================================
// Maps an .fbs field id to the generated VT_* vtable offset: VT_<FIELD> == (id + 2) * 2.
#define VT(field) (field + 2) * 2
static_assert(core::Se3TrackerPose::VT_POSE == VT(0));
static_assert(core::Se3TrackerPose::VT_IS_VALID == VT(1));

static_assert(core::Se3TrackerPoseTracked::VT_DATA == VT(0));

static_assert(core::Se3TrackerPoseRecord::VT_DATA == VT(0));
static_assert(core::Se3TrackerPoseRecord::VT_TIMESTAMP == VT(1));

// =============================================================================
// Compile-time verification of FlatBuffer field types.
// These ensure schema field types remain stable across changes.
// =============================================================================
#define TYPE(field) decltype(std::declval<core::Se3TrackerPose>().field())
static_assert(std::is_same_v<TYPE(pose), const core::Pose*>);
static_assert(std::is_same_v<TYPE(is_valid), bool>);


TEST_CASE("Se3TrackerPoseT default construction", "[se3_tracker][native]")
{
    auto se3_pose = std::make_unique<core::Se3TrackerPoseT>();

    // Default values.
    CHECK(se3_pose->pose == nullptr);
    CHECK(se3_pose->is_valid == false);
}

TEST_CASE("Se3TrackerPoseT serialization round-trip", "[se3_tracker][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(1024);

    // Create Se3TrackerPoseT with all fields set.
    auto original = std::make_unique<core::Se3TrackerPoseT>();
    core::Point position(1.5f, 2.5f, 3.5f);
    core::Quaternion orientation(0.0f, 0.0f, 0.7071068f, 0.7071068f); // 90 deg around Z (x, y, z, w).
    original->pose = std::make_shared<core::Pose>(position, orientation);
    original->is_valid = true;

    auto offset = core::Se3TrackerPose::Pack(builder, original.get());
    builder.Finish(offset);

    // Unpack to a fresh Se3TrackerPoseT and verify.
    auto fb = flatbuffers::GetRoot<core::Se3TrackerPose>(builder.GetBufferPointer());
    auto unpacked = std::make_unique<core::Se3TrackerPoseT>();
    fb->UnPackTo(unpacked.get());

    CHECK(unpacked->pose->position().x() == Catch::Approx(1.5f));
    CHECK(unpacked->pose->position().y() == Catch::Approx(2.5f));
    CHECK(unpacked->pose->position().z() == Catch::Approx(3.5f));
    // x and y must stay zero — guards against quaternion component-order regressions.
    CHECK(unpacked->pose->orientation().x() == Catch::Approx(0.0f));
    CHECK(unpacked->pose->orientation().y() == Catch::Approx(0.0f));
    CHECK(unpacked->pose->orientation().z() == Catch::Approx(0.7071068f).epsilon(0.0001));
    CHECK(unpacked->pose->orientation().w() == Catch::Approx(0.7071068f).epsilon(0.0001));
    CHECK(unpacked->is_valid == true);
}

// =============================================================================
// Se3TrackerPoseRecord tests (timestamp lives on the Record wrapper)
// =============================================================================
TEST_CASE("Se3TrackerPoseRecord round-trip with DeviceDataTimestamp", "[se3_tracker][flatbuffers]")
{
    flatbuffers::FlatBufferBuilder builder(1024);

    auto record = std::make_shared<core::Se3TrackerPoseRecordT>();
    record->data = std::make_shared<core::Se3TrackerPoseT>();
    core::Point position(1.0f, 2.0f, 3.0f);
    core::Quaternion orientation(0.0f, 0.0f, 0.0f, 1.0f);
    record->data->pose = std::make_shared<core::Pose>(position, orientation);
    record->data->is_valid = true;
    record->timestamp = std::make_shared<core::DeviceDataTimestamp>(1000000000LL, 2000000000LL, 3000000000LL);

    auto offset = core::Se3TrackerPoseRecord::Pack(builder, record.get());
    builder.Finish(offset);

    auto fb = flatbuffers::GetRoot<core::Se3TrackerPoseRecord>(builder.GetBufferPointer());
    auto unpacked = std::make_shared<core::Se3TrackerPoseRecordT>();
    fb->UnPackTo(unpacked.get());

    CHECK(unpacked->timestamp->available_time_local_common_clock() == 1000000000LL);
    CHECK(unpacked->timestamp->sample_time_local_common_clock() == 2000000000LL);
    CHECK(unpacked->timestamp->sample_time_raw_device_clock() == 3000000000LL);
    CHECK(unpacked->data->pose->position().x() == Catch::Approx(1.0f));
    CHECK(unpacked->data->is_valid == true);
}
