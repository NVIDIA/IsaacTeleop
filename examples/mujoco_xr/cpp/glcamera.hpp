// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

// One XR view's asymmetric fov -> the mjvGLCamera frustum fields MuJoCo builds
// its projection from. Free functions, no GPU and no MuJoCo state, so
// tests/test_projection.py can pin the convention headless.
//
// `frustum_width` is a HALF-width, and at 0 mjr_render derives the horizontal
// extent from the viewport aspect instead (render_gl3.c setView), which renders
// something plausible from a fov carrying nothing. Always set it; reject a fov
// that would leave it 0. mjvisualize.h calls the field "not used for
// rendering", which is wrong as of 3.11.0.

#include <array>
#include <cmath>
#include <stdexcept>

namespace mujoco_xr
{

// MuJoCo's own spelling and units: extents on the near plane, half_width
// symmetric about center.
struct Frustum
{
    float center = 0.0f;
    float half_width = 0.0f;
    float bottom = 0.0f;
    float top = 0.0f;
    float near_z = 0.0f;
    float far_z = 0.0f;
};

// fov_lrud is (left, right, up, down) radians -- viz::Fov's and XrFovf's field
// order, with left and down normally negative. No y flip here: OpenGL clip
// space is y-up like the fov, and the flip happens once, on readback.
inline Frustum frustum_from_fov(const std::array<float, 4>& fov_lrud, float near_z, float far_z)
{
    if (!(near_z > 0.0f) || !(far_z > near_z))
    {
        throw std::invalid_argument("mujoco_xr: need 0 < near_z < far_z");
    }
    const float left = near_z * std::tan(fov_lrud[0]);
    const float right = near_z * std::tan(fov_lrud[1]);
    const float top = near_z * std::tan(fov_lrud[2]);
    const float bottom = near_z * std::tan(fov_lrud[3]);

    Frustum f;
    f.center = 0.5f * (right + left);
    f.half_width = 0.5f * (right - left);
    f.bottom = bottom;
    f.top = top;
    f.near_z = near_z;
    f.far_z = far_z;

    // A default-constructed viz::Fov is all zeros, and a zero half_width is
    // exactly what turns the aspect-ratio fallback on. Refuse it.
    if (!(f.half_width > 0.0f) || !(f.top > f.bottom))
    {
        throw std::invalid_argument(
            "mujoco_xr: degenerate fov -- angle_right must exceed angle_left and angle_up must exceed "
            "angle_down. An all-zero fov means FrameInfo.views was never filled.");
    }
    return f;
}

// A view-space distance -> the depth handed to ProjectionLayer.submit():
// standard Z, near -> 0, far -> 1. NOT what MuJoCo writes -- mjr_render is
// reverse Z (glClipControl ZERO_TO_ONE, GL_GEQUAL, glClearDepth(0)), so the two
// differ by exactly `1 - d`, the subtraction in gl_readback.cpp's shader.
inline float submitted_depth(float distance, float near_z, float far_z)
{
    return far_z * (distance - near_z) / (distance * (far_z - near_z));
}

} // namespace mujoco_xr
