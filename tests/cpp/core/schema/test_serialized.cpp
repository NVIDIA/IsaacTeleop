// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for narrowing a Serialized<T> handle onto a table nested in its buffer.
// The handle's other states (empty, packed) are covered in test_pedals.cpp.

#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>
#include <schema/joint_state_generated.h>
#include <schema/serialized.hpp>
#include <schema/timestamp_generated.h>

#include <memory>
#include <utility>

namespace
{

core::JointStateOutputT make_native()
{
    auto joint = std::make_shared<core::JointStateT>();
    joint->name = "wrist";
    joint->position = 0.75f;

    core::JointStateOutputT native;
    native.joints.push_back(std::move(joint));
    return native;
}

//! Buffer owner that reports its own destruction, so a test can observe whether a handle
//! still holds a claim without dereferencing a pointer that may outlive its allocation.
struct TrackedBuffer
{
    TrackedBuffer(flatbuffers::DetachedBuffer&& buffer, bool& released) : buffer(std::move(buffer)), released(released)
    {
    }

    ~TrackedBuffer()
    {
        released = true;
    }

    flatbuffers::DetachedBuffer buffer;
    bool& released;
};

} // namespace

TEST_CASE("A narrowed handle outlives the handle it was narrowed from", "[serialized]")
{
    // The shape ReplayHandTrackerImpl::update relies on: it narrows onto the payload of a
    // record that is a function-local, and the narrowed handle is all that keeps the MCAP
    // bytes alive afterwards. Nothing else here may hold the buffer, so the parent is
    // confined to an inner scope.
    core::Serialized<core::JointState> nested;
    {
        const core::JointStateOutputT native = make_native();
        const auto output = core::pack<core::JointStateOutput>(native);
        nested = output.narrow(output->joints()->Get(0));
        REQUIRE(nested);
    }

    CHECK(nested->name()->str() == "wrist");
    CHECK(nested->position() == 0.75f);
}

TEST_CASE("Narrowing and copying share the owner rather than borrowing it", "[serialized]")
{
    // The check above reads through the narrowed handle, which cannot fail reliably: a
    // released buffer usually still holds its bytes, and this project builds without
    // sanitizers. So assert on ownership itself -- the owner reports when it is freed.
    const core::JointStateOutputT native = make_native();

    flatbuffers::FlatBufferBuilder fbb;
    fbb.Finish(core::JointStateOutput::Pack(fbb, &native));

    bool released = false;
    auto owner = std::make_shared<TrackedBuffer>(fbb.Release(), released);
    core::Serialized<core::JointStateOutput> output(
        owner, flatbuffers::GetRoot<core::JointStateOutput>(owner->buffer.data()));
    owner.reset();

    core::Serialized<core::JointState> nested = output.narrow(output->joints()->Get(0));
    core::Serialized<core::JointState> copy = nested;

    output.reset();
    nested.reset();
    CHECK_FALSE(released); // the copy alone must still hold the buffer

    copy.reset();
    CHECK(released); // and releasing the last handle must free it
}

TEST_CASE("Moving a handle empties the source", "[serialized]")
{
    core::JointStateOutputT native;
    native.joints.push_back(std::make_shared<core::JointStateT>());

    auto output = core::pack<core::JointStateOutput>(native);
    REQUIRE(output);

    const core::Serialized<core::JointStateOutput> moved = std::move(output);
    REQUIRE(moved);
    CHECK(moved->joints()->size() == 1);
    CHECK(!output);
    CHECK(output.get() == nullptr);

    auto source = core::pack<core::JointStateOutput>(native);
    core::Serialized<core::JointStateOutput> target;
    target = std::move(source);
    CHECK(target);
    CHECK(!source);
    CHECK(source.get() == nullptr);
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

TEST_CASE("An adopted handle can hand over the bytes it owns", "[serialized]")
{
    const core::JointStateOutputT native = make_native();
    const auto output = core::pack<core::JointStateOutput>(native);

    // The whole encoded buffer, ready for a sink that takes a pointer and a length.
    const auto bytes = output.buffer();
    REQUIRE_FALSE(bytes.empty());
    CHECK(flatbuffers::GetRoot<core::JointStateOutput>(bytes.data()) == output.get());

    // Narrowing inside the buffer does not carry it: those bytes are a buffer rooted at
    // JointStateOutput, not at the nested table, so handing them to a reader expecting one
    // would be wrong.
    const core::Serialized<core::JointState> nested = output.narrow(output->joints()->Get(0));
    REQUIRE(nested);
    CHECK(nested.buffer().empty());

    // Narrowing onto the handle's own table re-points at nothing, so it is a copy and the
    // bytes stay -- they are still a buffer rooted at JointStateOutput.
    const auto self = output.narrow(output.get());
    REQUIRE(self);
    CHECK(self.get() == output.get());
    CHECK(self.buffer().data() == bytes.data());
    CHECK(self.buffer().size() == bytes.size());
}

TEST_CASE("Emptying a handle drops the bytes with it", "[serialized]")
{
    const core::JointStateOutputT native = make_native();

    auto output = core::pack<core::JointStateOutput>(native);
    REQUIRE_FALSE(output.buffer().empty());
    output.reset();
    CHECK(output.buffer().empty());

    auto source = core::pack<core::JointStateOutput>(native);
    const auto moved = std::move(source);
    CHECK_FALSE(moved.buffer().empty());
    CHECK(source.buffer().empty());
}
