// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_head_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/head_bfbs_generated.h>
#include <schema/timestamp_generated.h>

#include <cassert>
#include <cstring>
#include <iostream>

namespace core
{

// ============================================================================
// ReplayHeadTrackerImpl
// ============================================================================

std::unique_ptr<HeadMcapViewers> ReplayHeadTrackerImpl::create_mcap_viewers(mcap::McapReader& reader,
                                                                            std::string_view base_name)
{
    return std::make_unique<HeadMcapViewers>(reader, base_name,
                                             std::vector<std::string>(HeadRecordingTraits::replay_channels.begin(),
                                                                      HeadRecordingTraits::replay_channels.end()));
}

ReplayHeadTrackerImpl::ReplayHeadTrackerImpl(mcap::McapReader& reader, std::string_view base_name)
    : mcap_viewers_(create_mcap_viewers(reader, base_name))
{
}

const HeadPoseTrackedT& ReplayHeadTrackerImpl::get_head() const
{
    return tracked_;
}

void ReplayHeadTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    if (mcap_viewers_)
    {
        auto result = mcap_viewers_->read(0);
        if (result)
        {
            tracked_ = std::move(*result);
        }
        else
        {
            std::cerr << "ReplayHeadTrackerImpl: head data not found" << std::endl;
            tracked_.data.reset();
        }
    }
}

} // namespace core
