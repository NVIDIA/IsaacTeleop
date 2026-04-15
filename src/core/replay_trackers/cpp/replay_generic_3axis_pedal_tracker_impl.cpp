// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_generic_3axis_pedal_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <oxr_utils/oxr_funcs.hpp>
#include <schema/pedals_bfbs_generated.h>
#include <schema/timestamp_generated.h>

#include <cassert>
#include <cstring>
#include <iostream>

namespace core
{

// ============================================================================
// ReplayGeneric3AxisPedalTrackerImpl
// ============================================================================

std::unique_ptr<PedalMcapViewers> ReplayGeneric3AxisPedalTrackerImpl::create_mcap_viewers(mcap::McapReader& reader,
                                                                                          std::string_view base_name)
{
    return std::make_unique<PedalMcapViewers>(reader, base_name,
                                              std::vector<std::string>(PedalRecordingTraits::replay_channels.begin(),
                                                                       PedalRecordingTraits::replay_channels.end()));
}

ReplayGeneric3AxisPedalTrackerImpl::ReplayGeneric3AxisPedalTrackerImpl(mcap::McapReader& reader,
                                                                       std::string_view base_name)
    : mcap_viewers_(create_mcap_viewers(reader, base_name))
{
}

const Generic3AxisPedalOutputTrackedT& ReplayGeneric3AxisPedalTrackerImpl::get_data() const
{
    return tracked_;
}

void ReplayGeneric3AxisPedalTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    if (mcap_viewers_)
    {
        auto pedal_data = mcap_viewers_->read(0);
        if (pedal_data)
        {
            tracked_.data = *pedal_data;
        }
        else
        {
            std::cerr << "ReplayGeneric3AxisPedalTrackerImpl: pedal data not found" << std::endl;
            tracked_.data.reset();
        }
    }
}

} // namespace core
