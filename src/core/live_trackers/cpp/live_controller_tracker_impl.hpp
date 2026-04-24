// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/controller_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <schema/controller_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using ControllerMcapChannels = McapTrackerChannels<ControllerSnapshotRecord, ControllerSnapshot>;

class LiveControllerTrackerImpl : public IControllerTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return { XR_NVX1_ACTION_CONTEXT_EXTENSION_NAME };
    }
    static std::unique_ptr<ControllerMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                        std::string_view base_name);

    LiveControllerTrackerImpl(const OpenXRSessionHandles& handles, std::unique_ptr<ControllerMcapChannels> mcap_channels);
    ~LiveControllerTrackerImpl() = default;

    LiveControllerTrackerImpl(const LiveControllerTrackerImpl&) = delete;
    LiveControllerTrackerImpl& operator=(const LiveControllerTrackerImpl&) = delete;
    LiveControllerTrackerImpl(LiveControllerTrackerImpl&&) = delete;
    LiveControllerTrackerImpl& operator=(LiveControllerTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const ControllerSnapshotTrackedT& get_left_controller() const override;
    const ControllerSnapshotTrackedT& get_right_controller() const override;

private:
    const OpenXRCoreFunctions core_funcs_;
    XrTimeConverter time_converter_;

    XrSession session_;
    XrSpace base_space_;

    XrPath left_hand_path_;
    XrPath right_hand_path_;

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
    XrAction menu_click_action_;
    XrAction squeeze_value_action_;
    XrAction trigger_value_action_;

    XrSpacePtr left_grip_space_;
    XrSpacePtr right_grip_space_;
    XrSpacePtr left_aim_space_;
    XrSpacePtr right_aim_space_;

    ControllerSnapshotTrackedT left_tracked_;
    ControllerSnapshotTrackedT right_tracked_;
    int64_t last_update_time_ = 0;

    std::unique_ptr<ControllerMcapChannels> mcap_channels_;
};

} // namespace core
