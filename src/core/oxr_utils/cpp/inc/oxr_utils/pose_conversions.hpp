// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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

// Convert core::ControllerPose (FlatBuffers) to XrPosef, reporting validity through
// out_valid. The pose is converted either way -- its contents are unspecified while
// out_valid is false, per the rule the pose schemas state. Callers that need a defined
// filler take identity_posef() below.
inline XrPosef to_xr_posef(const core::ControllerPose& controller_pose, bool& out_valid)
{
    out_valid = controller_pose.is_valid();
    return to_xr_posef(controller_pose.pose());
}

// Identity filler returned alongside out_valid=false, matching the "pose contents are
// unspecified while invalid" rule the pose schemas state.
inline XrPosef identity_posef()
{
    return XrPosef{ { 0.0f, 0.0f, 0.0f, 1.0f }, { 0.0f, 0.0f, 0.0f } };
}

// Nullable overload. Reading a snapshot through its encoded accessors makes each nested
// table independently optional at the format level, so absence is answered here -- once --
// rather than left for every caller to null-check.
inline XrPosef to_xr_posef(const core::ControllerPose* controller_pose, bool& out_valid)
{
    if (controller_pose == nullptr)
    {
        out_valid = false;
        return identity_posef();
    }
    return to_xr_posef(*controller_pose, out_valid);
}

// Convert core::ControllerSnapshot to get aim pose as XrPosef.
inline XrPosef get_aim_pose(const core::ControllerSnapshot& snapshot, bool& out_valid)
{
    return to_xr_posef(snapshot.aim_pose(), out_valid);
}

// Convert core::ControllerSnapshot to get grip pose as XrPosef.
inline XrPosef get_grip_pose(const core::ControllerSnapshot& snapshot, bool& out_valid)
{
    return to_xr_posef(snapshot.grip_pose(), out_valid);
}

} // namespace oxr_utils
