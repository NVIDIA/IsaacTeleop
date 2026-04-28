// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <glm/glm.hpp>
#include <glm/gtc/quaternion.hpp>

#include <cstdint>

namespace viz
{

// Display resolution in pixels. Used by VizSession::Config and FrameInfo.
struct Resolution
{
    uint32_t width = 0;
    uint32_t height = 0;
};

// 3D pose in OpenXR stage space: right-handed, Y-up, meters for distance,
// orientation as a unit quaternion. Default-constructed is identity.
//
// Memory layout note: glm::vec3 is `float[3]`, glm::quat is `float[4]` in
// (w, x, y, z) order — matching glm's constructor argument order, NOT
// XrQuaternionf's (x, y, z, w) wire order. Conversions at the OpenXR
// boundary (in viz_xr) handle the swizzle.
struct Pose3D
{
    glm::vec3 position{ 0.0f, 0.0f, 0.0f };
    glm::quat orientation{ 1.0f, 0.0f, 0.0f, 0.0f }; // w, x, y, z (identity)
};

// Per-eye field of view in radians, measured from the forward axis.
// Conventions match XrFovf: angle_left is typically negative (left of forward),
// angle_right typically positive (right of forward).
struct Fov
{
    float angle_left = 0.0f;
    float angle_right = 0.0f;
    float angle_up = 0.0f;
    float angle_down = 0.0f;
};

// Per-view rendering parameters for one frame. Layers receive a vector of
// these (one per eye in XR; a single identity-pose entry in window/offscreen
// modes) and use them to position their content in 3D space.
//
// Matrices are glm::mat4 (column-major float[16] under the hood, GLSL-
// compatible). For Vulkan / CUDA upload use glm::value_ptr(mat) to get a
// raw float* — no copy needed.
struct ViewInfo
{
    glm::mat4 view_matrix{ 1.0f }; // identity
    glm::mat4 projection_matrix{ 1.0f }; // identity
    Fov fov{};
    Pose3D pose{};
};

} // namespace viz
