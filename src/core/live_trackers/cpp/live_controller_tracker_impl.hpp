// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/controller_tracker_base.hpp>
#include <openxr/openxr.h>
#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <schema/controller_generated.h>

namespace core
{

// OpenXR-backed implementation of ControllerTrackerImpl.
class LiveControllerTrackerImpl : public ControllerTrackerImpl
{
public:
    explicit LiveControllerTrackerImpl(const OpenXRSessionHandles& handles);
    ~LiveControllerTrackerImpl() = default;

    LiveControllerTrackerImpl(const LiveControllerTrackerImpl&) = delete;
    LiveControllerTrackerImpl& operator=(const LiveControllerTrackerImpl&) = delete;
    LiveControllerTrackerImpl(LiveControllerTrackerImpl&&) = delete;
    LiveControllerTrackerImpl& operator=(LiveControllerTrackerImpl&&) = delete;

    bool update(XrTime time) override;
    void serialize_all(size_t channel_index, const RecordCallback& callback) const override;
    const ControllerSnapshotTrackedT& get_left_controller() const override;
    const ControllerSnapshotTrackedT& get_right_controller() const override;

private:
    const OpenXRCoreFunctions core_funcs_;
    XrTimeConverter time_converter_;

    XrSession session_;
    XrSpace base_space_;

    XrPath left_hand_path_;
    XrPath right_hand_path_;

    // Action context -- declared before action_set_ so it outlives it.
    ActionContextFunctions action_ctx_funcs_;
    XrInstanceActionContextPtr instance_action_context_;
    XrSessionActionContextPtr session_action_context_;

    XrActionSetPtr action_set_;
    XrAction grip_pose_action_;
    XrAction aim_pose_action_;
    XrAction primary_click_action_;
    XrAction secondary_click_action_;
    XrAction thumbstick_action_;
    XrAction thumbstick_click_action_;
    XrAction squeeze_value_action_;
    XrAction trigger_value_action_;

    XrSpacePtr left_grip_space_;
    XrSpacePtr right_grip_space_;
    XrSpacePtr left_aim_space_;
    XrSpacePtr right_aim_space_;

    ControllerSnapshotTrackedT left_tracked_;
    ControllerSnapshotTrackedT right_tracked_;
    XrTime last_update_time_ = 0;
};

} // namespace core
