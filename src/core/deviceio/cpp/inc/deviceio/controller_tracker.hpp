// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <schema/controller_bfbs_generated.h>
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

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    std::string_view get_schema_name() const override
    {
        return SCHEMA_NAME;
    }

    std::string_view get_schema_text() const override
    {
        return std::string_view(reinterpret_cast<const char*>(ControllerSnapshotRecordBinarySchema::data()),
                                ControllerSnapshotRecordBinarySchema::size());
    }

    std::vector<std::string> get_record_channels() const override
    {
        return { "left_controller", "right_controller" };
    }

    // Query methods - public API for getting controller data (tracked.data is null when inactive)
    const ControllerSnapshotTrackedT& get_left_controller(const DeviceIOSession& session) const;
    const ControllerSnapshotTrackedT& get_right_controller(const DeviceIOSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "ControllerTracker";
    static constexpr const char* SCHEMA_NAME = "core.ControllerSnapshotRecord";

    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    class Impl : public ITrackerImpl
    {
    public:
        explicit Impl(const OpenXRSessionHandles& handles);

        // Override from ITrackerImpl
        bool update(XrTime time) override;

        void serialize_all(size_t channel_index, const RecordCallback& callback) const override;

        const ControllerSnapshotTrackedT& get_left_controller() const;
        const ControllerSnapshotTrackedT& get_right_controller() const;

    private:
        const OpenXRCoreFunctions core_funcs_;
        XrTimeConverter time_converter_;

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

        // Controller data (tracked.data is null when inactive)
        ControllerSnapshotTrackedT left_tracked_;
        ControllerSnapshotTrackedT right_tracked_;
        XrTime last_update_time_ = 0;
    };
};

} // namespace core
