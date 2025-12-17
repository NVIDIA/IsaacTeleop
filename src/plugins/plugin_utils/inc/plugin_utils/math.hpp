// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>

namespace plugin_utils
{

constexpr XrPosef multiply_poses(const XrPosef& a, const XrPosef& b)
{
    XrPosef result{};

    // Quaternion multiplication: result = a * b
    float qw = a.orientation.w, qx = a.orientation.x, qy = a.orientation.y, qz = a.orientation.z;
    float rw = b.orientation.w, rx = b.orientation.x, ry = b.orientation.y, rz = b.orientation.z;

    result.orientation.w = qw * rw - qx * rx - qy * ry - qz * rz;
    result.orientation.x = qw * rx + qx * rw + qy * rz - qz * ry;
    result.orientation.y = qw * ry - qx * rz + qy * rw + qz * rx;
    result.orientation.z = qw * rz + qx * ry - qy * rx + qz * rw;

    // Position: result = a.pos + a.rot * b.pos
    float vx = b.position.x, vy = b.position.y, vz = b.position.z;

    // t = 2 * cross(q.xyz, v)
    float tx = 2.0f * (qy * vz - qz * vy);
    float ty = 2.0f * (qz * vx - qx * vz);
    float tz = 2.0f * (qx * vy - qy * vx);

    // v' = v + q.w * t + cross(q.xyz, t)
    float rot_x = vx + qw * tx + (qy * tz - qz * ty);
    float rot_y = vy + qw * ty + (qz * tx - qx * tz);
    float rot_z = vz + qw * tz + (qx * ty - qy * tx);

    result.position.x = a.position.x + rot_x;
    result.position.y = a.position.y + rot_y;
    result.position.z = a.position.z + rot_z;

    return result;
}

} // namespace plugin_utils
