// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Unit tests for Resolution, Pose3D, Fov, and ViewInfo plain-old-data types.

#include <catch2/catch_test_macros.hpp>
#include <glm/gtc/type_ptr.hpp>
#include <viz/core/viz_types.hpp>

using viz::Fov;
using viz::Pose3D;
using viz::Resolution;
using viz::ViewInfo;

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
    // glm::quat constructor order is (w, x, y, z); identity = (1, 0, 0, 0).
    CHECK(p.orientation.w == 1.0f);
    CHECK(p.orientation.x == 0.0f);
    CHECK(p.orientation.y == 0.0f);
    CHECK(p.orientation.z == 0.0f);
}

TEST_CASE("Pose3D aggregate construction preserves fields", "[unit][viz_types]")
{
    // glm::quat literal order is (w, x, y, z).
    Pose3D p{ glm::vec3{ 1.0f, 2.0f, 3.0f }, glm::quat{ 0.4f, 0.1f, 0.2f, 0.3f } };
    CHECK(p.position.x == 1.0f);
    CHECK(p.position.y == 2.0f);
    CHECK(p.position.z == 3.0f);
    CHECK(p.orientation.w == 0.4f);
    CHECK(p.orientation.x == 0.1f);
    CHECK(p.orientation.y == 0.2f);
    CHECK(p.orientation.z == 0.3f);
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

TEST_CASE("ViewInfo default-constructed is identity", "[unit][viz_types]")
{
    ViewInfo v{};
    // glm::mat4{1.0f} is the identity matrix.
    CHECK(v.view_matrix == glm::mat4{ 1.0f });
    CHECK(v.projection_matrix == glm::mat4{ 1.0f });
    CHECK(v.pose.position == glm::vec3{ 0.0f });
    CHECK(v.pose.orientation == glm::quat{ 1.0f, 0.0f, 0.0f, 0.0f });
}

TEST_CASE("ViewInfo matrices are GLSL-compatible column-major float[16]", "[unit][viz_types]")
{
    // Critical contract: glm::mat4 must be POD-equivalent to float[16] so we
    // can upload directly to Vulkan uniform buffers / push constants without
    // a copy. glm::value_ptr returns the same pointer as &mat[0][0].
    static_assert(sizeof(glm::mat4) == sizeof(float) * 16);
    ViewInfo v{};
    const float* raw = glm::value_ptr(v.view_matrix);
    REQUIRE(raw != nullptr);
    // Column-major identity layout: 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1.
    for (int col = 0; col < 4; ++col)
    {
        for (int row = 0; row < 4; ++row)
        {
            const float expected = (col == row) ? 1.0f : 0.0f;
            CHECK(raw[col * 4 + row] == expected);
        }
    }
}
