// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <cstdint>

namespace core::viz
{

// Display resolution in pixels. Used by VizSession::Config and FrameInfo.
struct Resolution
{
    uint32_t width = 0;
    uint32_t height = 0;
};

// 3D pose in OpenXR stage space: right-handed, Y-up, meters for distance,
// orientation as quaternion. Default-constructed is identity.
struct Pose3D
{
    struct Position
    {
        float x = 0.0f;
        float y = 0.0f;
        float z = 0.0f;
    };

    struct Orientation
    {
        float x = 0.0f;
        float y = 0.0f;
        float z = 0.0f;
        float w = 1.0f;
    };

    Position position{};
    Orientation orientation{};
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

} // namespace core::viz
