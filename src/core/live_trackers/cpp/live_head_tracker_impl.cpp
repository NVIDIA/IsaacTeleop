// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_head_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/head_bfbs_generated.h>

#include <cstring>
#include <iostream>
#include <stdexcept>

namespace core
{

// ============================================================================
// LiveHeadTrackerImpl
// ============================================================================

std::unique_ptr<HeadMcapChannels> LiveHeadTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                            std::string_view base_name)
{
    return std::make_unique<HeadMcapChannels>(
        writer, base_name, HeadRecordingTraits::schema_name,
        std::vector<std::string>(HeadRecordingTraits::channels.begin(), HeadRecordingTraits::channels.end()));
}

LiveHeadTrackerImpl::LiveHeadTrackerImpl(const OpenXRSessionHandles& handles,
                                         std::unique_ptr<HeadMcapChannels> mcap_channels)
    : core_funcs_(OpenXRCoreFunctions::load(handles.instance, handles.xrGetInstanceProcAddr)),
      time_converter_(handles),
      base_space_(handles.space),
      view_space_(createReferenceSpace(core_funcs_,
                                       handles.session,
                                       { .type = XR_TYPE_REFERENCE_SPACE_CREATE_INFO,
                                         .referenceSpaceType = XR_REFERENCE_SPACE_TYPE_VIEW,
                                         .poseInReferenceSpace = { .orientation = { 0, 0, 0, 1 } } })),
      tracked_{},
      mcap_channels_(std::move(mcap_channels))
{
}

void LiveHeadTrackerImpl::update(int64_t graph_time_ns)
{
    int64_t now_ns = os_monotonic_now_ns();
    XrTime xr_time = time_converter_.convert_monotonic_ns_to_xrtime(now_ns);

    XrSpaceLocation location{ XR_TYPE_SPACE_LOCATION };
    XrResult result = core_funcs_.xrLocateSpace(view_space_.get(), base_space_, xr_time, &location);

    if (XR_FAILED(result))
    {
        tracked_.data.reset();
        throw std::runtime_error("[HeadTracker] xrLocateSpace failed: " + std::to_string(result));
    }

    bool position_valid = (location.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) != 0;
    bool orientation_valid = (location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT) != 0;

    if (!tracked_.data)
    {
        tracked_.data = std::make_shared<HeadPoseT>();
    }

    tracked_.data->is_valid = position_valid && orientation_valid;

    if (tracked_.data->is_valid)
    {
        Point position(location.pose.position.x, location.pose.position.y, location.pose.position.z);
        Quaternion orientation(location.pose.orientation.x, location.pose.orientation.y, location.pose.orientation.z,
                               location.pose.orientation.w);
        tracked_.data->pose = std::make_shared<Pose>(position, orientation);
    }
    else
    {
        // Keep pose populated whenever data is present; validity is indicated by is_valid.
        tracked_.data->pose = std::make_shared<Pose>();
    }

    if (mcap_channels_)
    {
        // TODO: Replace with actual client-reported sample/available timestamps
        // once the runtime exposes per-sample timing metadata.
        DeviceDataTimestamp timestamp(now_ns, now_ns, static_cast<int64_t>(xr_time));
        mcap_channels_->write(0, graph_time_ns, timestamp, tracked_.data);
    }
}

const HeadPoseTrackedT& LiveHeadTrackerImpl::get_head() const
{
    return tracked_;
}

} // namespace core
