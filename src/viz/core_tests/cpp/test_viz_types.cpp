// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for Resolution, Pose3D, and Fov plain-old-data types.

#include <catch2/catch_test_macros.hpp>
#include <viz/core/viz_types.hpp>

using viz::Fov;
using viz::Pose3D;
using viz::Resolution;

TEST_CASE("Resolution default-constructed is zero", "[unit][viz_types]")
{
    Resolution r{};
    CHECK(r.width == 0);
    CHECK(r.height == 0);
}

TEST_CASE("Resolution aggregate construction", "[unit][viz_types]")
{
    Resolution r{ 1920, 1080 };
    CHECK(r.width == 1920);
    CHECK(r.height == 1080);
}

TEST_CASE("Pose3D default-constructed is identity", "[unit][viz_types]")
{
    Pose3D p{};
    CHECK(p.position.x == 0.0f);
    CHECK(p.position.y == 0.0f);
    CHECK(p.position.z == 0.0f);
    CHECK(p.orientation.x == 0.0f);
    CHECK(p.orientation.y == 0.0f);
    CHECK(p.orientation.z == 0.0f);
    CHECK(p.orientation.w == 1.0f);
}

TEST_CASE("Pose3D aggregate construction preserves fields", "[unit][viz_types]")
{
    Pose3D p{ { 1.0f, 2.0f, 3.0f }, { 0.1f, 0.2f, 0.3f, 0.4f } };
    CHECK(p.position.x == 1.0f);
    CHECK(p.position.y == 2.0f);
    CHECK(p.position.z == 3.0f);
    CHECK(p.orientation.x == 0.1f);
    CHECK(p.orientation.y == 0.2f);
    CHECK(p.orientation.z == 0.3f);
    CHECK(p.orientation.w == 0.4f);
}

TEST_CASE("Fov default-constructed is zero", "[unit][viz_types]")
{
    Fov f{};
    CHECK(f.angle_left == 0.0f);
    CHECK(f.angle_right == 0.0f);
    CHECK(f.angle_up == 0.0f);
    CHECK(f.angle_down == 0.0f);
}

TEST_CASE("Fov aggregate construction", "[unit][viz_types]")
{
    Fov f{ -1.0f, 1.0f, 0.5f, -0.5f };
    CHECK(f.angle_left == -1.0f);
    CHECK(f.angle_right == 1.0f);
    CHECK(f.angle_up == 0.5f);
    CHECK(f.angle_down == -0.5f);
}
