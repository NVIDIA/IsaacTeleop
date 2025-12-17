// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <openxr/openxr.h>
#include <plugin_utils/math.hpp>

namespace
{

constexpr bool float_eq(float a, float b, float epsilon = 0.0001f)
{
    float diff = a - b;
    return (diff < epsilon) && (diff > -epsilon);
}

constexpr bool test_multiply_poses()
{
    // 1. Identity * Identity = Identity
    XrPosef id = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
    XrPosef res1 = plugin_utils::multiply_poses(id, id);

    if (!float_eq(res1.position.x, 0.0f))
        return false;
    if (!float_eq(res1.position.y, 0.0f))
        return false;
    if (!float_eq(res1.position.z, 0.0f))
        return false;
    if (!float_eq(res1.orientation.w, 1.0f))
        return false;

    // 2. Translation * Identity = Translation
    XrPosef t1 = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 1.0f, 2.0f, 3.0f } };
    XrPosef res2 = plugin_utils::multiply_poses(t1, id);
    if (!float_eq(res2.position.x, 1.0f))
        return false;
    if (!float_eq(res2.position.y, 2.0f))
        return false;
    if (!float_eq(res2.position.z, 3.0f))
        return false;

    // 3. Identity * Translation = Translation (in local frame of id, which is same)
    XrPosef res3 = plugin_utils::multiply_poses(id, t1);
    if (!float_eq(res3.position.x, 1.0f))
        return false;
    if (!float_eq(res3.position.y, 2.0f))
        return false;
    if (!float_eq(res3.position.z, 3.0f))
        return false;

    // 4. Rotation 90 deg around X (q = {sin(45), 0, 0, cos(45)}) -> {0.7071, 0, 0, 0.7071}
    //    multiply by point {0, 1, 0} -> should become {0, 0, 1}

    float inv_sqrt2 = 0.70710678f;
    XrPosef rotX90 = { { inv_sqrt2, 0.0f, 0.0f, inv_sqrt2 }, { 0.0f, 0.0f, 0.0f } };
    XrPosef posY1 = { { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 1.0f, 0.0f } };

    XrPosef res4 = plugin_utils::multiply_poses(rotX90, posY1);

    // Check position: should be {0, 0, 1}
    if (!float_eq(res4.position.x, 0.0f))
        return false;
    if (!float_eq(res4.position.y, 0.0f))
        return false;
    if (!float_eq(res4.position.z, 1.0f))
        return false;

    return true;
}

} // namespace

// Compile-time assertion (still active)
static_assert(test_multiply_poses(), "plugin_utils::multiply_poses failed compile-time tests");

TEST_CASE("Math functions work at runtime", "[math]")
{
    REQUIRE(test_multiply_poses());
}
