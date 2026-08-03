// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_generic_3axis_pedal_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/pedals_bfbs_generated.h>
#include <schema/serialized.hpp>
#include <schema/timestamp_generated.h>
#include <schema/tracked.hpp>

#include <cassert>
#include <cstring>
#include <iostream>

namespace core
{

// ============================================================================
// ReplayGeneric3AxisPedalTrackerImpl
// ============================================================================

ReplayGeneric3AxisPedalTrackerImpl::ReplayGeneric3AxisPedalTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                                                                       std::string_view base_name)
    : mcap_viewers_(
          std::make_unique<PedalMcapViewers>(std::move(reader),
                                             base_name,
                                             std::vector<std::string>(PedalRecordingTraits::replay_channels.begin(),
                                                                      PedalRecordingTraits::replay_channels.end())))
{
}

const Serialized<Generic3AxisPedalOutput>& ReplayGeneric3AxisPedalTrackerImpl::get_data() const
{
    return tracked_;
}

void ReplayGeneric3AxisPedalTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    auto record = mcap_viewers_->read_serialized(0);
    if (record)
    {
        tracked_ = record.narrow(payload(record));
    }
    else
    {
        std::cerr << "ReplayGeneric3AxisPedalTrackerImpl: pedal data not found" << std::endl;
        tracked_.reset();
    }
}

} // namespace core
