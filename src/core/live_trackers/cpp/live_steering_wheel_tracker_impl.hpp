// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "inc/live_trackers/schema_tracker.hpp"

#include <deviceio_trackers/steering_wheel_tracker.hpp>
#include <oxr_utils/oxr_session_handles.hpp>
#include <schema/steering_wheel_generated.h>

#include <cstdint>
#include <memory>
#include <string>
#include <string_view>
#include <vector>

namespace core
{

using SteeringWheelMcapChannels = McapTrackerChannels<SteeringWheelOutputRecord, SteeringWheelOutput>;
using SteeringWheelSchemaTracker = SchemaTracker<SteeringWheelOutputRecord, SteeringWheelOutput>;

class LiveSteeringWheelTrackerImpl : public ISteeringWheelTrackerImpl
{
public:
    static std::vector<std::string> required_extensions()
    {
        return SchemaTrackerBase::get_required_extensions();
    }
    static std::unique_ptr<SteeringWheelMcapChannels> create_mcap_channels(mcap::McapWriter& writer,
                                                                           std::string_view base_name);

    LiveSteeringWheelTrackerImpl(const OpenXRSessionHandles& handles,
                                 const SteeringWheelTracker* tracker,
                                 std::unique_ptr<SteeringWheelMcapChannels> mcap_channels);

    LiveSteeringWheelTrackerImpl(const LiveSteeringWheelTrackerImpl&) = delete;
    LiveSteeringWheelTrackerImpl& operator=(const LiveSteeringWheelTrackerImpl&) = delete;
    LiveSteeringWheelTrackerImpl(LiveSteeringWheelTrackerImpl&&) = delete;
    LiveSteeringWheelTrackerImpl& operator=(LiveSteeringWheelTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const SteeringWheelOutputTrackedT& get_data() const override;

private:
    std::unique_ptr<SteeringWheelMcapChannels> mcap_channels_;
    SteeringWheelSchemaTracker m_schema_reader;
    SteeringWheelOutputTrackedT m_tracked;
};

} // namespace core
