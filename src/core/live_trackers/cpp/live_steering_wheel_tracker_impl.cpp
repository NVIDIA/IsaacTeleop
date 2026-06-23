// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_steering_wheel_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/steering_wheel_bfbs_generated.h>

namespace core
{

namespace
{

SchemaTrackerConfig make_steering_wheel_tensor_config(const SteeringWheelTracker* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    cfg.tensor_identifier = "steering_wheel";
    cfg.localized_name = "SteeringWheelTracker";
    return cfg;
}

} // namespace

std::unique_ptr<SteeringWheelMcapChannels> LiveSteeringWheelTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                              std::string_view base_name)
{
    return std::make_unique<SteeringWheelMcapChannels>(
        writer, base_name, SteeringWheelRecordingTraits::schema_name,
        std::vector<std::string>(SteeringWheelRecordingTraits::recording_channels.begin(),
                                 SteeringWheelRecordingTraits::recording_channels.end()));
}

LiveSteeringWheelTrackerImpl::LiveSteeringWheelTrackerImpl(const OpenXRSessionHandles& handles,
                                                           const SteeringWheelTracker* tracker,
                                                           std::unique_ptr<SteeringWheelMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      m_schema_reader(handles,
                      make_steering_wheel_tensor_config(tracker),
                      mcap_channels_.get(),
                      /*mcap_channel_index=*/0,
                      /*mcap_channel_tracked_index=*/1)
{
}

void LiveSteeringWheelTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    m_schema_reader.update(m_tracked.data);
}

const SteeringWheelOutputTrackedT& LiveSteeringWheelTrackerImpl::get_data() const
{
    return m_tracked;
}

} // namespace core
