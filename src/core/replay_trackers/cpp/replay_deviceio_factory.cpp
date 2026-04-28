// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/replay_trackers/replay_deviceio_factory.hpp"

#include "replay_controller_tracker_impl.hpp"
#include "replay_full_body_tracker_pico_impl.hpp"
#include "replay_generic_3axis_pedal_tracker_impl.hpp"
#include "replay_hand_tracker_impl.hpp"
#include "replay_head_tracker_impl.hpp"

#include <deviceio_trackers/controller_tracker.hpp>
#include <deviceio_trackers/full_body_tracker_pico.hpp>
#include <deviceio_trackers/generic_3axis_pedal_tracker.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <deviceio_trackers/head_tracker.hpp>
#include <mcap/reader.hpp>

#include <cassert>
#include <memory>
#include <stdexcept>
#include <string>

namespace core
{

namespace
{

std::unique_ptr<mcap::McapReader> open_reader(const std::string& filename)
{
    auto reader = std::make_unique<mcap::McapReader>();
    auto status = reader->open(filename);
    if (!status.ok())
    {
        throw std::runtime_error("ReplayDeviceIOFactory: failed to open MCAP file '" + filename + "': " + status.message);
    }
    return reader;
}


std::unique_ptr<ITrackerImpl> try_create_head_impl(ReplayDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const HeadTracker*>(&tracker);
    return typed ? factory.create_head_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_hand_impl(ReplayDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const HandTracker*>(&tracker);
    return typed ? factory.create_hand_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_controller_impl(ReplayDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const ControllerTracker*>(&tracker);
    return typed ? factory.create_controller_tracker_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_full_body_pico_impl(ReplayDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const FullBodyTrackerPico*>(&tracker);
    return typed ? factory.create_full_body_tracker_pico_impl(typed) : nullptr;
}

std::unique_ptr<ITrackerImpl> try_create_generic_pedal_impl(ReplayDeviceIOFactory& factory, const ITracker& tracker)
{
    auto* typed = dynamic_cast<const Generic3AxisPedalTracker*>(&tracker);
    return typed ? factory.create_generic_3axis_pedal_tracker_impl(typed) : nullptr;
}

using TryCreateFn = std::unique_ptr<ITrackerImpl> (*)(ReplayDeviceIOFactory&, const ITracker&);

inline const TryCreateFn k_tracker_dispatch[] = {
    &try_create_head_impl,           &try_create_hand_impl,          &try_create_controller_impl,
    &try_create_full_body_pico_impl, &try_create_generic_pedal_impl,
};

} // namespace

ReplayDeviceIOFactory::ReplayDeviceIOFactory(std::string filename,
                                             const std::vector<std::pair<const ITracker*, std::string>>& tracker_names)
    : filename_(std::move(filename))
{
    for (const auto& [tracker, name] : tracker_names)
    {
        auto [it, inserted] = name_map_.emplace(tracker, name);
        if (!inserted)
        {
            throw std::invalid_argument("ReplayDeviceIOFactory: duplicate tracker pointer for channel name '" + name +
                                        "' (already mapped as '" + it->second + "')");
        }
    }
}

std::unique_ptr<ITrackerImpl> ReplayDeviceIOFactory::create_tracker_impl(const ITracker& tracker)
{
    for (const auto& try_create : k_tracker_dispatch)
    {
        if (std::unique_ptr<ITrackerImpl> impl = try_create(*this, tracker))
        {
            return impl;
        }
    }
    throw std::invalid_argument("ReplayDeviceIOFactory::create_tracker_impl: unsupported tracker type '" +
                                std::string(tracker.get_name()) + "'");
}

std::string_view ReplayDeviceIOFactory::get_name(const ITracker* tracker) const
{
    auto it = name_map_.find(tracker);
    assert(it != name_map_.end() && "get_name called for tracker not in name_map_");
    return it->second;
}

std::unique_ptr<IHeadTrackerImpl> ReplayDeviceIOFactory::create_head_tracker_impl(const HeadTracker* tracker)
{
    return std::make_unique<ReplayHeadTrackerImpl>(open_reader(filename_), get_name(tracker));
}

std::unique_ptr<IHandTrackerImpl> ReplayDeviceIOFactory::create_hand_tracker_impl(const HandTracker* tracker)
{
    return std::make_unique<ReplayHandTrackerImpl>(open_reader(filename_), get_name(tracker));
}

std::unique_ptr<IControllerTrackerImpl> ReplayDeviceIOFactory::create_controller_tracker_impl(const ControllerTracker* tracker)
{
    return std::make_unique<ReplayControllerTrackerImpl>(open_reader(filename_), get_name(tracker));
}

std::unique_ptr<IFullBodyTrackerPicoImpl> ReplayDeviceIOFactory::create_full_body_tracker_pico_impl(
    const FullBodyTrackerPico* tracker)
{
    return std::make_unique<ReplayFullBodyTrackerPicoImpl>(open_reader(filename_), get_name(tracker));
}

std::unique_ptr<IGeneric3AxisPedalTrackerImpl> ReplayDeviceIOFactory::create_generic_3axis_pedal_tracker_impl(
    const Generic3AxisPedalTracker* tracker)
{
    return std::make_unique<ReplayGeneric3AxisPedalTrackerImpl>(open_reader(filename_), get_name(tracker));
}

} // namespace core
