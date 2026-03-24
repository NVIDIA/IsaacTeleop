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
#include <oxr_utils/oxr_time.hpp>

#include <cassert>
#include <set>
#include <stdexcept>
#include <string>

namespace core
{

namespace
{

template <typename TrackerT, typename ImplT>
bool try_add_extensions(const ITracker& tracker, std::set<std::string>& out)
{
    if (dynamic_cast<const TrackerT*>(&tracker))
    {
        for (const auto& ext : ImplT::required_extensions())
            out.insert(ext);
        return true;
    }
    return false;
}

std::unique_ptr<ITrackerImpl> try_create_head_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const HeadTracker*>(&tracker);
    return typed ? factory.create_head_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_hand_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const HandTracker*>(&tracker);
    return typed ? factory.create_hand_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_controller_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const ControllerTracker*>(&tracker);
    return typed ? factory.create_controller_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_full_body_pico_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const FullBodyTrackerPico*>(&tracker);
    return typed ? factory.create_full_body_tracker_pico_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_generic_pedal_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const Generic3AxisPedalTracker*>(&tracker);
    return typed ? factory.create_generic_3axis_pedal_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_oak_impl(LiveDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const FrameMetadataTrackerOak*>(&tracker);
    return typed ? factory.create_frame_metadata_tracker_oak_impl(typed) : nullptr;
}

using CollectExtensionsFn = bool (*)(const ITracker&, std::set<std::string>&);
using TryCreateFn = std::unique_ptr<ITrackerImpl> (*)(LiveDeviceIOFactory&, const ITracker&);

struct TrackerDispatchEntry
{
    CollectExtensionsFn collect_extensions;
    TryCreateFn try_create;
};

// Shared tracker dispatch table for both extension collection and impl creation.
inline const TrackerDispatchEntry k_tracker_dispatch[] = {
    { &try_add_extensions<HeadTracker, LiveHeadTrackerImpl>, &try_create_head_impl },
    { &try_add_extensions<HandTracker, LiveHandTrackerImpl>, &try_create_hand_impl },
    { &try_add_extensions<ControllerTracker, LiveControllerTrackerImpl>, &try_create_controller_impl },
    { &try_add_extensions<FullBodyTrackerPico, LiveFullBodyTrackerPicoImpl>, &try_create_full_body_pico_impl },
    { &try_add_extensions<Generic3AxisPedalTracker, LiveGeneric3AxisPedalTrackerImpl>, &try_create_generic_pedal_impl },
    { &try_add_extensions<FrameMetadataTrackerOak, LiveFrameMetadataTrackerOakImpl>, &try_create_oak_impl },
};

} // namespace

std::vector<std::string> LiveDeviceIOFactory::get_required_extensions(const std::vector<std::shared_ptr<ITracker>>& trackers)
{
    std::set<std::string> all;

    // DeviceIOSession always owns an XrTimeConverter; match session requirements even with zero trackers.
    for (const auto& ext : XrTimeConverter::get_required_extensions())
        all.insert(ext);

    for (const auto& tracker : trackers)
    {
        if (!tracker)
            throw std::invalid_argument("LiveDeviceIOFactory: null tracker in trackers list");

        bool matched = false;
        for (const auto& dispatch : k_tracker_dispatch)
        {
            if (dispatch.collect_extensions(*tracker, all))
            {
                matched = true;
                break;
            }
        }

        if (!matched)
        {
            throw std::invalid_argument("LiveDeviceIOFactory::get_required_extensions: unsupported tracker type '" +
                                        std::string(tracker->get_name()) + "'");
        }
    }

    return { all.begin(), all.end() };
}

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

std::unique_ptr<ITrackerImpl> LiveDeviceIOFactory::create_tracker_impl(const ITracker& tracker)
{
    for (const auto& dispatch : k_tracker_dispatch)
    {
        if (std::unique_ptr<ITrackerImpl> impl = dispatch.try_create(*this, tracker))
        {
            return impl;
        }
    }
    throw std::invalid_argument("LiveDeviceIOFactory::create_tracker_impl: unsupported tracker type '" +
                                std::string(tracker.get_name()) + "'");
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
