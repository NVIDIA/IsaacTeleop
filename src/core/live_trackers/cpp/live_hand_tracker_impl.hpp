// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/hand_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <openxr/openxr.h>
#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <schema/hand_generated.h>

#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using HandMcapChannels = McapTrackerChannels<HandPoseRecord, HandPose>;

class LiveHandTrackerImpl : public HandTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return { XR_EXT_HAND_TRACKING_EXTENSION_NAME };
    }
    static std::unique_ptr<HandMcapChannels> create_mcap_channels(mcap::McapWriter& writer, std::string_view base_name);

    LiveHandTrackerImpl(const OpenXRSessionHandles& handles, std::unique_ptr<HandMcapChannels> mcap_channels);
    ~LiveHandTrackerImpl();

    LiveHandTrackerImpl(const LiveHandTrackerImpl&) = delete;
    LiveHandTrackerImpl& operator=(const LiveHandTrackerImpl&) = delete;
    LiveHandTrackerImpl(LiveHandTrackerImpl&&) = delete;
    LiveHandTrackerImpl& operator=(LiveHandTrackerImpl&&) = delete;

    bool update(XrTime time) override;
    const HandPoseTrackedT& get_left_hand() const override;
    const HandPoseTrackedT& get_right_hand() const override;

private:
    bool update_hand(XrHandTrackerEXT tracker, XrTime time, HandPoseTrackedT& tracked);

    XrTimeConverter time_converter_;
    XrSpace base_space_;

    XrHandTrackerEXT left_hand_tracker_;
    XrHandTrackerEXT right_hand_tracker_;

    HandPoseTrackedT left_tracked_;
    HandPoseTrackedT right_tracked_;
    XrTime last_update_time_ = 0;

    PFN_xrCreateHandTrackerEXT pfn_create_hand_tracker_;
    PFN_xrDestroyHandTrackerEXT pfn_destroy_hand_tracker_;
    PFN_xrLocateHandJointsEXT pfn_locate_hand_joints_;

    std::unique_ptr<HandMcapChannels> mcap_channels_;
};

} // namespace core
