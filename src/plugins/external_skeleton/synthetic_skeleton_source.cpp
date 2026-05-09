// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "synthetic_skeleton_source.hpp"

#include <cmath>

namespace plugins
{
namespace external_skeleton
{

namespace
{

constexpr float kPi = 3.14159265358979323846f;

// Stylized rest-pose offsets in metres for each ExternalSkeletonJoint index.
// Coordinates: +X right, +Y up, +Z forward (matches schema/pose.fbs convention).
constexpr float kRestPositions[core::ExternalSkeletonJoint_NUM_JOINTS][3] = {
    { 0.00f, 0.00f, 0.00f }, // ROOT
    { 0.00f, 0.95f, 0.00f }, // HIPS
    { 0.00f, 1.15f, 0.00f }, // SPINE
    { 0.00f, 1.35f, 0.00f }, // CHEST
    { 0.00f, 1.55f, 0.00f }, // NECK
    { 0.00f, 1.70f, 0.00f }, // HEAD
    { -0.18f, 1.50f, 0.00f }, // LEFT_SHOULDER
    { -0.18f, 1.30f, 0.00f }, // LEFT_UPPER_ARM
    { -0.18f, 1.05f, 0.00f }, // LEFT_LOWER_ARM
    { -0.18f, 0.85f, 0.00f }, // LEFT_HAND
    { 0.18f, 1.50f, 0.00f }, // RIGHT_SHOULDER
    { 0.18f, 1.30f, 0.00f }, // RIGHT_UPPER_ARM
    { 0.18f, 1.05f, 0.00f }, // RIGHT_LOWER_ARM
    { 0.18f, 0.85f, 0.00f }, // RIGHT_HAND
};

core::Pose make_pose(float x, float y, float z)
{
    return core::Pose(core::Point(x, y, z), core::Quaternion(0.0f, 0.0f, 0.0f, 1.0f));
}

} // namespace

SyntheticSkeletonSource::SyntheticSkeletonSource() : start_(std::chrono::steady_clock::now())
{
}

bool SyntheticSkeletonSource::poll(core::ExternalSkeletonPoseT& out, int64_t& raw_device_clock_ns)
{
    const auto now = std::chrono::steady_clock::now();
    const float t = std::chrono::duration<float>(now - start_).count();
    const float wave = 0.25f * std::sin(2.0f * kPi * 0.5f * t); // ~0.5 Hz wave

    if (!out.joints)
    {
        out.joints = std::make_shared<core::ExternalSkeletonJoints>();
    }

    for (uint32_t i = 0; i < core::ExternalSkeletonJoint_NUM_JOINTS; ++i)
    {
        float x = kRestPositions[i][0];
        const float y = kRestPositions[i][1];
        const float z = kRestPositions[i][2];

        // Animate both hands and forearms left/right to produce a visible wave.
        const bool is_arm = (i == core::ExternalSkeletonJoint_LEFT_LOWER_ARM ||
                             i == core::ExternalSkeletonJoint_LEFT_HAND ||
                             i == core::ExternalSkeletonJoint_RIGHT_LOWER_ARM ||
                             i == core::ExternalSkeletonJoint_RIGHT_HAND);
        if (is_arm)
        {
            x += wave * (x < 0.0f ? -1.0f : 1.0f);
        }

        out.joints->mutable_joints()->Mutate(i, core::BodyJointPose(make_pose(x, y, z), /*is_valid=*/true));
    }

    out.all_joint_poses_tracked = true;
    out.source_id = source_id();

    // No device clock available for synthetic data; let the caller substitute
    // the local monotonic clock by leaving this at zero (sentinel).
    raw_device_clock_ns = 0;
    return true;
}

} // namespace external_skeleton
} // namespace plugins
