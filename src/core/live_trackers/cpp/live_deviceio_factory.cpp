// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/live_trackers/live_deviceio_factory.hpp"

#include "live_controller_tracker_impl.hpp"
#include "live_frame_metadata_tracker_oak_impl.hpp"
#include "live_full_body_tracker_pico_impl.hpp"
#include "live_generic_3axis_pedal_tracker_impl.hpp"
#include "live_hand_tracker_impl.hpp"
#include "live_head_tracker_impl.hpp"

#include <deviceio_trackers/controller_tracker.hpp>
#include <deviceio_trackers/frame_metadata_tracker_oak.hpp>
#include <deviceio_trackers/full_body_tracker_pico.hpp>
#include <deviceio_trackers/generic_3axis_pedal_tracker.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <deviceio_trackers/head_tracker.hpp>

#include <stdexcept>

namespace core
{

LiveDeviceIOFactory::LiveDeviceIOFactory(const OpenXRSessionHandles& handles,
                                         mcap::McapWriter* writer,
                                         const std::vector<std::pair<const ITracker*, std::string>>& tracker_names)
    : handles_(handles), writer_(writer)
{
    for (const auto& [tracker, name] : tracker_names)
    {
        auto [it, inserted] = name_map_.emplace(tracker, name);
        if (!inserted)
        {
            throw std::invalid_argument("LiveDeviceIOFactory: duplicate tracker pointer for channel name '" + name +
                                        "' (already mapped as '" + it->second + "')");
        }
    }
}

bool LiveDeviceIOFactory::should_record(const ITracker* tracker) const
{
    return writer_ && name_map_.count(tracker);
}

std::string_view LiveDeviceIOFactory::get_name(const ITracker* tracker) const
{
    auto it = name_map_.find(tracker);
    assert(it != name_map_.end() && "get_name called for tracker not in name_map_ (call should_record first)");
    return it->second;
}

std::unique_ptr<HeadTrackerImpl> LiveDeviceIOFactory::create_head_tracker_impl(const HeadTracker* tracker)
{
    std::unique_ptr<HeadMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveHeadTrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveHeadTrackerImpl>(handles_, std::move(channels));
}

std::unique_ptr<HandTrackerImpl> LiveDeviceIOFactory::create_hand_tracker_impl(const HandTracker* tracker)
{
    std::unique_ptr<HandMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveHandTrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveHandTrackerImpl>(handles_, std::move(channels));
}

std::unique_ptr<ControllerTrackerImpl> LiveDeviceIOFactory::create_controller_tracker_impl(const ControllerTracker* tracker)
{
    std::unique_ptr<ControllerMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveControllerTrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveControllerTrackerImpl>(handles_, std::move(channels));
}

std::unique_ptr<FullBodyTrackerPicoImpl> LiveDeviceIOFactory::create_full_body_tracker_pico_impl(
    const FullBodyTrackerPico* tracker)
{
    std::unique_ptr<FullBodyMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveFullBodyTrackerPicoImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveFullBodyTrackerPicoImpl>(handles_, std::move(channels));
}

std::unique_ptr<Generic3AxisPedalTrackerImpl> LiveDeviceIOFactory::create_generic_3axis_pedal_tracker_impl(
    const Generic3AxisPedalTracker* tracker)
{
    std::unique_ptr<PedalMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveGeneric3AxisPedalTrackerImpl::create_mcap_channels(*writer_, get_name(tracker));
    }
    return std::make_unique<LiveGeneric3AxisPedalTrackerImpl>(handles_, tracker, std::move(channels));
}

std::unique_ptr<FrameMetadataTrackerOakImpl> LiveDeviceIOFactory::create_frame_metadata_tracker_oak_impl(
    const FrameMetadataTrackerOak* tracker)
{
    std::unique_ptr<OakMcapChannels> channels;
    if (should_record(tracker))
    {
        channels = LiveFrameMetadataTrackerOakImpl::create_mcap_channels(*writer_, get_name(tracker), tracker);
    }
    return std::make_unique<LiveFrameMetadataTrackerOakImpl>(handles_, tracker, std::move(channels));
}

} // namespace core
