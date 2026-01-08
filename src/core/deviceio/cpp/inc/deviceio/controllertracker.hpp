// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/controller_generated.h>

#include <memory>

namespace core
{

// Controller tracker - tracks both left and right controllers
// Updates all controller state (poses + inputs) each frame
class ControllerTracker : public ITracker
{
public:
    // Public API - what external users see
    std::vector<std::string> get_required_extensions() const override;
    std::string get_name() const override;

    // Get complete controller data (both left and right controllers)
    const ControllerDataT& get_controller_data(const DeviceIOSession& session) const;

private:
    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    class Impl : public ITrackerImpl
    {
    public:
        explicit Impl(const OpenXRSessionHandles& handles);

        // Override from ITrackerImpl
        bool update(XrTime time) override;

        const ControllerDataT& get_controller_data() const;

    private:
        const OpenXRCoreFunctions core_funcs_;

        XrSession session_;
        XrSpace base_space_;

        // Paths for both hands
        XrPath left_hand_path_;
        XrPath right_hand_path_;

        // Actions - simplified to only the inputs we care about
        XrActionSetPtr action_set_;
        XrAction grip_pose_action_;
        XrAction aim_pose_action_;
        XrAction primary_click_action_;
        XrAction secondary_click_action_;
        XrAction thumbstick_action_;
        XrAction thumbstick_click_action_;
        XrAction squeeze_value_action_;
        XrAction trigger_value_action_;

        // Action spaces for both hands
        XrSpacePtr left_grip_space_;
        XrSpacePtr right_grip_space_;
        XrSpacePtr left_aim_space_;
        XrSpacePtr right_aim_space_;

        // Controller data for both hands (table wrapper with struct snapshots)
        ControllerDataT controller_data_;
    };
};

} // namespace core
