// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <openxr/openxr.h>
#include <schema/controller_generated.h>

namespace oxr_utils
{

// Convert core::Pose (FlatBuffers) to XrPosef (OpenXR)
inline XrPosef to_xr_posef(const core::Pose& pose)
{
    XrPosef result{};
    result.position.x = pose.position().x();
    result.position.y = pose.position().y();
    result.position.z = pose.position().z();
    result.orientation.x = pose.orientation().x();
    result.orientation.y = pose.orientation().y();
    result.orientation.z = pose.orientation().z();
    result.orientation.w = pose.orientation().w();
    return result;
}

// Convert core::ControllerPose (FlatBuffers) to XrPosef with validity check
// Returns identity pose if invalid
inline XrPosef to_xr_posef(const core::ControllerPose& controller_pose, bool& out_valid)
{
    out_valid = controller_pose.is_valid();
    return to_xr_posef(controller_pose.pose());
}

// Convert core::ControllerSnapshotT to get aim pose as XrPosef
inline XrPosef get_aim_pose(const core::ControllerSnapshotT& snapshot, bool& out_valid)
{
    out_valid = snapshot.aim_pose->is_valid();
    return to_xr_posef(snapshot.aim_pose->pose());
}

// Convert core::ControllerSnapshotT to get grip pose as XrPosef
inline XrPosef get_grip_pose(const core::ControllerSnapshotT& snapshot, bool& out_valid)
{
    out_valid = snapshot.grip_pose->is_valid();
    return to_xr_posef(snapshot.grip_pose->pose());
}

} // namespace oxr_utils
