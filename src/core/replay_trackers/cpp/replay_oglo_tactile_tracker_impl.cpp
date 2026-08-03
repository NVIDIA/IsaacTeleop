// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_oglo_tactile_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/oglo_tactile_bfbs_generated.h>
#include <schema/serialized.hpp>
#include <schema/timestamp_generated.h>
#include <schema/tracked.hpp>

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

const Serialized<OgloGloveSample>& ReplayOgloTactileTrackerImpl::get_data() const
{
    return tracked_;
}

void ReplayOgloTactileTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    auto record = mcap_viewers_->read_serialized(0);
    if (record)
    {
        tracked_ = record.narrow(payload(record));
    }
    else
    {
        std::cerr << "ReplayOgloTactileTrackerImpl: glove data not found" << std::endl;
        tracked_.reset();
    }
}

} // namespace core
