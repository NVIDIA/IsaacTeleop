// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for narrowing a Serialized<T> handle onto a table nested in its buffer.
// The handle's other states (empty, packed, pack_optional) are covered in test_pedals.cpp.

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>
#include <schema/joint_state_generated.h>
#include <schema/serialized.hpp>
#include <schema/timestamp_generated.h>

#include <memory>

TEST_CASE("Narrowing to a nested table shares the parent buffer", "[serialized]")
{
    auto joint = std::make_shared<core::JointStateT>();
    joint->name = "wrist";
    joint->position = 0.75f;

    core::JointStateOutputT native;
    native.joints.push_back(std::move(joint));

    const auto output = core::pack<core::JointStateOutput>(native);
    core::Serialized<core::JointState> nested = output.narrow(output->joints()->Get(0));

    REQUIRE(nested);
    CHECK(nested->name()->str() == "wrist");

    // The narrowed handle keeps the buffer alive on its own: one allocation backs a whole
    // tree of views, and a copy outlives the handle it came from.
    core::Serialized<core::JointState> survivor = nested;
    nested.reset();
    CHECK(!nested);
    CHECK(survivor->position() == 0.75f);
}

TEST_CASE("Narrowing an absent nested table yields an empty handle", "[serialized]")
{
    core::JointStateOutputRecordT native;
    native.timestamp = std::make_shared<core::DeviceDataTimestamp>(1, 2, 3);

    const auto record = core::pack<core::JointStateOutputRecord>(native);

    REQUIRE(record);
    REQUIRE(record->data() == nullptr);
    CHECK(!record.narrow(record->data()));
}
