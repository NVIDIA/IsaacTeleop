// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Hand joint generation
#pragma once

#include <openxr/openxr.h>

namespace plugins
{
namespace controller_synthetic_hands
{

class HandGenerator
{
public:
    HandGenerator() = default;
    ~HandGenerator() = default;

    // Generate hand joints in world space from a world-space wrist pose
    void generate(XrHandJointLocationEXT* joints, const XrPosef& wrist_pose, bool is_left_hand, float curl = 0.0f);

    // Generate hand joints in controller-relative space (for space-based injection)
    void generate_relative(XrHandJointLocationEXT* joints, bool is_left_hand, float curl = 0.0f);

private:
    struct Vec3
    {
        float x, y, z;
    };

    XrVector3f rotate_vector(const XrVector3f& v, const XrQuaternionf& q);
    XrQuaternionf quaternion_look_at(const XrVector3f& direction, const XrVector3f& up);
    void calculate_positions(XrHandJointLocationEXT* joints, const XrPosef& wrist_pose, bool is_left_hand, float curl);
    void calculate_orientations(XrHandJointLocationEXT* joints, const XrPosef& wrist_pose);
};

} // namespace controller_synthetic_hands
} // namespace plugins
