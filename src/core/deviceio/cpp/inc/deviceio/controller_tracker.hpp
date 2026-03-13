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

    std::shared_ptr<ILiveTrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;
    std::shared_ptr<IReplayTrackerImpl> create_replay_tracker(const ITrackerSession& session) const override;

    // Tracker-specific interface: both live and replay impls implement this so the tracker
    // can use get_tracker_impl() and cast to IImpl& without caring which impl type it is.
    struct IImpl
    {
        virtual ~IImpl() = default;
        virtual const ControllerSnapshotTrackedT& get_left_controller() const = 0;
        virtual const ControllerSnapshotTrackedT& get_right_controller() const = 0;
    };

    class Impl : public ILiveTrackerImpl, public IImpl
    {
    public:
        explicit Impl(const OpenXRSessionHandles& handles);

        // Override from ILiveTrackerImpl
        bool update_live(int64_t system_monotonic_time_ns) override;

        void serialize_all(size_t channel_index, const RecordCallback& callback) const override;

        const ControllerSnapshotTrackedT& get_left_controller() const override;
        const ControllerSnapshotTrackedT& get_right_controller() const override;

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
        int64_t last_update_time_ns_ = 0; // monotonic ns; XrTime only for OpenXR calls
    };

    // Dummy replay impl: returns default (inactive) data; update_replay is a no-op.
    class ReplayImpl : public IReplayTrackerImpl, public IImpl
    {
    public:
        explicit ReplayImpl(const ITrackerSession& session);

        bool update_replay(int64_t replay_time_ns) override;

        const ControllerSnapshotTrackedT& get_left_controller() const override;
        const ControllerSnapshotTrackedT& get_right_controller() const override;

    private:
        const ITrackerSession* session_;
        ControllerSnapshotTrackedT left_tracked_;
        ControllerSnapshotTrackedT right_tracked_;
    };
};

} // namespace core
