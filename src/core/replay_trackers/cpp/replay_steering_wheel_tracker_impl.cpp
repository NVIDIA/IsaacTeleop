// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_steering_wheel_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/steering_wheel_bfbs_generated.h>
#include <schema/timestamp_generated.h>

#include <iostream>

namespace core
{

ReplaySteeringWheelTrackerImpl::ReplaySteeringWheelTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                                                               std::string_view base_name)
    : mcap_viewers_(std::make_unique<SteeringWheelMcapViewers>(
          std::move(reader),
          base_name,
          std::vector<std::string>(SteeringWheelRecordingTraits::replay_channels.begin(),
                                   SteeringWheelRecordingTraits::replay_channels.end())))
{
}

const SteeringWheelOutputTrackedT& ReplaySteeringWheelTrackerImpl::get_data() const
{
    return tracked_;
}

void ReplaySteeringWheelTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    auto record = mcap_viewers_->read(0);
    if (record)
    {
        tracked_.data = std::move(record->data);
    }
    else
    {
        std::cerr << "ReplaySteeringWheelTrackerImpl: steering wheel data not found" << std::endl;
        tracked_.data.reset();
    }
}

} // namespace core
