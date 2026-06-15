// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/steering_wheel_tracker_base.hpp>
#include <mcap/tracker_channels.hpp>
#include <schema/steering_wheel_generated.h>

#include <cstdint>
#include <memory>
#include <string_view>

namespace core
{

using SteeringWheelMcapViewers = McapTrackerViewers<SteeringWheelOutputRecord>;

class ReplaySteeringWheelTrackerImpl : public ISteeringWheelTrackerImpl
{
public:
    ReplaySteeringWheelTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name);

    ReplaySteeringWheelTrackerImpl(const ReplaySteeringWheelTrackerImpl&) = delete;
    ReplaySteeringWheelTrackerImpl& operator=(const ReplaySteeringWheelTrackerImpl&) = delete;
    ReplaySteeringWheelTrackerImpl(ReplaySteeringWheelTrackerImpl&&) = delete;
    ReplaySteeringWheelTrackerImpl& operator=(ReplaySteeringWheelTrackerImpl&&) = delete;

    void update(int64_t monotonic_time_ns) override;
    const SteeringWheelOutputTrackedT& get_data() const override;

private:
    SteeringWheelOutputTrackedT tracked_;
    std::unique_ptr<SteeringWheelMcapViewers> mcap_viewers_;
};

} // namespace core
