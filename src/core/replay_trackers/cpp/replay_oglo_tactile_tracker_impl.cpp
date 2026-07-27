// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_oglo_tactile_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/oglo_tactile_bfbs_generated.h>
#include <schema/timestamp_generated.h>

#include <cassert>
#include <cstring>
#include <iostream>

namespace core
{

// ============================================================================
// ReplayOgloTactileTrackerImpl
// ============================================================================

ReplayOgloTactileTrackerImpl::ReplayOgloTactileTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                                                           std::string_view base_name)
    : mcap_viewers_(
          std::make_unique<OgloMcapViewers>(std::move(reader),
                                            base_name,
                                            std::vector<std::string>(OgloRecordingTraits::replay_channels.begin(),
                                                                     OgloRecordingTraits::replay_channels.end())))
{
}

const OgloGloveSampleTrackedT& ReplayOgloTactileTrackerImpl::get_data() const
{
    return tracked_;
}

void ReplayOgloTactileTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    auto record = mcap_viewers_->read(0);
    if (record)
    {
        tracked_.data = std::move(record->data);
    }
    else
    {
        std::cerr << "ReplayOgloTactileTrackerImpl: glove data not found" << std::endl;
        tracked_.data.reset();
    }
}

} // namespace core
