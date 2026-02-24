// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for the generated Generic3AxisPedalOutput FlatBuffer struct.

#include <catch2/catch_approx.hpp>
#include <catch2/catch_test_macros.hpp>
#include <flatbuffers/flatbuffers.h>

// Include generated FlatBuffer headers.
#include <schema/pedals_generated.h>

#include <type_traits>

#define VT(field) (field + 2) * 2
// Only keep Record VT asserts
static_assert(core::Generic3AxisPedalOutputRecord::VT_DATA == VT(0));
static_assert(std::is_trivially_copyable_v<core::Generic3AxisPedalOutput>);

// =============================================================================
// Generic3AxisPedalOutput Tests
// =============================================================================
TEST_CASE("Generic3AxisPedalOutput default construction", "[pedals][native]")
{
    core::Generic3AxisPedalOutput output;

    // is_active should be false by default.
    CHECK(output.is_active() == false);
    // Float fields should be zero by default.
    CHECK(output.left_pedal() == 0.0f);
    CHECK(output.right_pedal() == 0.0f);
    CHECK(output.rudder() == 0.0f);
}

TEST_CASE("Generic3AxisPedalOutput can handle is_active value properly", "[pedals][native]")
{
    core::Generic3AxisPedalOutput output;

    // Default is_active should be false.
    CHECK(output.is_active() == false);

    // Set is_active to true.
    output.mutate_is_active(true);
    CHECK(output.is_active() == true);
}

TEST_CASE("Generic3AxisPedalOutput can store timestamp", "[pedals][native]")
{
    core::Generic3AxisPedalOutput output;

    // Create timestamp.
    core::Timestamp timestamp(1000000000, 2000000000);
    output.mutable_timestamp() = timestamp;

    CHECK(output.timestamp().device_time() == 1000000000);
    CHECK(output.timestamp().common_time() == 2000000000);
}

TEST_CASE("Generic3AxisPedalOutput can store pedal values", "[pedals][native]")
{
    core::Generic3AxisPedalOutput output;

    output.mutate_left_pedal(0.75f);
    output.mutate_right_pedal(0.25f);
    output.mutate_rudder(0.5f);

    CHECK(output.left_pedal() == Catch::Approx(0.75f));
    CHECK(output.right_pedal() == Catch::Approx(0.25f));
    CHECK(output.rudder() == Catch::Approx(0.5f));
}

TEST_CASE("Generic3AxisPedalOutput can store full output", "[pedals][native]")
{
    core::Generic3AxisPedalOutput output;

    // Set all fields.
    output.mutate_is_active(true);
    core::Timestamp timestamp(3000000000, 4000000000);
    output.mutable_timestamp() = timestamp;
    output.mutate_left_pedal(1.0f);
    output.mutate_right_pedal(0.0f);
    output.mutate_rudder(-0.5f);

    CHECK(output.is_active() == true);
    CHECK(output.timestamp().device_time() == 3000000000);
    CHECK(output.left_pedal() == Catch::Approx(1.0f));
    CHECK(output.right_pedal() == Catch::Approx(0.0f));
    CHECK(output.rudder() == Catch::Approx(-0.5f));
}

// =============================================================================
// Realistic Foot Pedal Scenarios
// =============================================================================
TEST_CASE("Generic3AxisPedalOutput full forward press", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutput output;
    output.mutate_is_active(true);
    core::Timestamp timestamp(1000000, 1000000);
    output.mutable_timestamp() = timestamp;
    output.mutate_left_pedal(1.0f);
    output.mutate_right_pedal(1.0f);
    output.mutate_rudder(0.0f);

    CHECK(output.is_active() == true);
    CHECK(output.left_pedal() == Catch::Approx(1.0f));
    CHECK(output.right_pedal() == Catch::Approx(1.0f));
    CHECK(output.rudder() == Catch::Approx(0.0f));
}

TEST_CASE("Generic3AxisPedalOutput left turn with rudder", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutput output;
    output.mutate_is_active(true);
    core::Timestamp timestamp(2000000, 2000000);
    output.mutable_timestamp() = timestamp;
    output.mutate_left_pedal(0.5f);
    output.mutate_right_pedal(0.5f);
    output.mutate_rudder(-1.0f); // Full left rudder.

    CHECK(output.rudder() == Catch::Approx(-1.0f));
}

TEST_CASE("Generic3AxisPedalOutput right turn with rudder", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutput output;
    output.mutate_is_active(true);
    core::Timestamp timestamp(3000000, 3000000);
    output.mutable_timestamp() = timestamp;
    output.mutate_left_pedal(0.5f);
    output.mutate_right_pedal(0.5f);
    output.mutate_rudder(1.0f); // Full right rudder.

    CHECK(output.rudder() == Catch::Approx(1.0f));
}

TEST_CASE("Generic3AxisPedalOutput differential braking", "[pedals][scenario]")
{
    // Simulating differential braking (left brake only).
    core::Generic3AxisPedalOutput output;
    output.mutate_is_active(true);
    core::Timestamp timestamp(4000000, 4000000);
    output.mutable_timestamp() = timestamp;
    output.mutate_left_pedal(0.0f); // Left brake applied.
    output.mutate_right_pedal(0.8f); // Right pedal pressed.
    output.mutate_rudder(0.0f);

    CHECK(output.left_pedal() == Catch::Approx(0.0f));
    CHECK(output.right_pedal() == Catch::Approx(0.8f));
}

TEST_CASE("Generic3AxisPedalOutput neutral position", "[pedals][scenario]")
{
    core::Generic3AxisPedalOutput output;
    output.mutate_is_active(true);
    core::Timestamp timestamp(5000000, 5000000);
    output.mutable_timestamp() = timestamp;
    output.mutate_left_pedal(0.0f);
    output.mutate_right_pedal(0.0f);
    output.mutate_rudder(0.0f);

    CHECK(output.left_pedal() == Catch::Approx(0.0f));
    CHECK(output.right_pedal() == Catch::Approx(0.0f));
    CHECK(output.rudder() == Catch::Approx(0.0f));
}

// =============================================================================
// Edge Cases
// =============================================================================
TEST_CASE("Generic3AxisPedalOutput with negative values", "[pedals][edge]")
{
    // Although pedal values are typically 0-1, test negative values.
    core::Generic3AxisPedalOutput output;
    output.mutate_left_pedal(-0.5f);
    output.mutate_right_pedal(-0.25f);
    output.mutate_rudder(-1.0f);

    CHECK(output.left_pedal() == Catch::Approx(-0.5f));
    CHECK(output.right_pedal() == Catch::Approx(-0.25f));
    CHECK(output.rudder() == Catch::Approx(-1.0f));
}

TEST_CASE("Generic3AxisPedalOutput with values greater than 1", "[pedals][edge]")
{
    // Test values exceeding typical range.
    core::Generic3AxisPedalOutput output;
    output.mutate_left_pedal(1.5f);
    output.mutate_right_pedal(2.0f);
    output.mutate_rudder(1.5f);

    CHECK(output.left_pedal() == Catch::Approx(1.5f));
    CHECK(output.right_pedal() == Catch::Approx(2.0f));
    CHECK(output.rudder() == Catch::Approx(1.5f));
}

TEST_CASE("Generic3AxisPedalOutput with large timestamp values", "[pedals][edge]")
{
    core::Generic3AxisPedalOutput output;
    output.mutate_is_active(true);
    int64_t max_int64 = 9223372036854775807;
    core::Timestamp timestamp(max_int64, max_int64 - 1000);
    output.mutable_timestamp() = timestamp;
    output.mutate_left_pedal(0.5f);

    CHECK(output.timestamp().device_time() == max_int64);
    CHECK(output.timestamp().common_time() == max_int64 - 1000);
}

TEST_CASE("Generic3AxisPedalOutput with is_active false", "[pedals][edge]")
{
    core::Generic3AxisPedalOutput output;
    output.mutate_is_active(false);
    core::Timestamp timestamp(1000, 2000);
    output.mutable_timestamp() = timestamp;
    output.mutate_left_pedal(0.5f);
    output.mutate_right_pedal(0.5f);
    output.mutate_rudder(0.0f);

    // Verify is_active is false but other data is still present.
    CHECK(output.is_active() == false);
    CHECK(output.left_pedal() == Catch::Approx(0.5f));
    CHECK(output.right_pedal() == Catch::Approx(0.5f));
    CHECK(output.rudder() == Catch::Approx(0.0f));
}
