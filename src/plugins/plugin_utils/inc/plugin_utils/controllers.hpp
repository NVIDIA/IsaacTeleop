// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Controller input tracking
#pragma once

#include <openxr/openxr.h>

#include <stdexcept>
#include <string>

namespace plugin_utils
{

struct ControllerPose
{
    XrPosef grip_pose;
    XrPosef aim_pose;
    bool grip_valid = false;
    bool aim_valid = false;
    float trigger_value = 0.0f; // 0.0 = not pressed, 1.0 = fully pressed
};

class Controllers
{
public:
    Controllers(XrInstance instance, XrSession session, XrSpace reference_space);
    ~Controllers();

    // Non-copyable
    Controllers(const Controllers&) = delete;
    Controllers& operator=(const Controllers&) = delete;

    // Movable (default move operations might be unsafe if we need to nullify handles,
    // so we'll delete them for simplicity unless needed, or implement custom move if strict RAII)
    // For now, making them non-movable to simplify resource management logic unless required.
    Controllers(Controllers&&) = delete;
    Controllers& operator=(Controllers&&) = delete;

    void update(XrTime time);

    const ControllerPose& left() const
    {
        return left_;
    }
    const ControllerPose& right() const
    {
        return right_;
    }

    // Get controller spaces for space-based hand injection
    XrSpace left_grip_space() const
    {
        return left_grip_space_;
    }
    XrSpace right_grip_space() const
    {
        return right_grip_space_;
    }
    XrSpace left_aim_space() const
    {
        return left_aim_space_;
    }
    XrSpace right_aim_space() const
    {
        return right_aim_space_;
    }

private:
    void create_actions(XrInstance instance);
    void setup_action_spaces(XrSession session);
    void locate_pose(XrSpace space, XrTime time, XrPosef& pose, bool& is_valid);
    void cleanup();

    XrSession session_ = XR_NULL_HANDLE;
    XrSpace reference_space_ = XR_NULL_HANDLE;

    XrActionSet action_set_ = XR_NULL_HANDLE;
    XrAction grip_pose_action_ = XR_NULL_HANDLE;
    XrAction aim_pose_action_ = XR_NULL_HANDLE;
    XrAction trigger_action_ = XR_NULL_HANDLE;

    XrPath left_hand_path_ = XR_NULL_PATH;
    XrPath right_hand_path_ = XR_NULL_PATH;

    XrSpace left_grip_space_ = XR_NULL_HANDLE;
    XrSpace right_grip_space_ = XR_NULL_HANDLE;
    XrSpace left_aim_space_ = XR_NULL_HANDLE;
    XrSpace right_aim_space_ = XR_NULL_HANDLE;

    ControllerPose left_;
    ControllerPose right_;
};

} // namespace plugin_utils
