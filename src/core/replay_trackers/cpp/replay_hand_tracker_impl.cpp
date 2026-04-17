// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_hand_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/hand_bfbs_generated.h>
#include <schema/timestamp_generated.h>

#include <cassert>
#include <cstring>
#include <iostream>

namespace core
{

// ============================================================================
// ReplayHandTrackerImpl
// ============================================================================

std::unique_ptr<HandMcapViewers> ReplayHandTrackerImpl::create_mcap_viewers(mcap::McapReader& reader,
                                                                            std::string_view base_name)
{
    return std::make_unique<HandMcapViewers>(reader, base_name,
                                             std::vector<std::string>(HandRecordingTraits::replay_channels.begin(),
                                                                      HandRecordingTraits::replay_channels.end()));
}

ReplayHandTrackerImpl::ReplayHandTrackerImpl(mcap::McapReader& reader, std::string_view base_name)
    : mcap_viewers_(create_mcap_viewers(reader, base_name))
{
}

const HandPoseTrackedT& ReplayHandTrackerImpl::get_left_hand() const
{
    return left_tracked_;
}

const HandPoseTrackedT& ReplayHandTrackerImpl::get_right_hand() const
{
    return right_tracked_;
}

void ReplayHandTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    if (mcap_viewers_)
    {
        auto left_result = mcap_viewers_->read(0);
        auto right_result = mcap_viewers_->read(1);
        if (left_result)
        {
            left_tracked_ = std::move(*left_result);
        }
        else
        {
            std::cerr << "ReplayHandTrackerImpl: left hand data not found" << std::endl;
            left_tracked_.data.reset();
        }

        if (right_result)
        {
            right_tracked_ = std::move(*right_result);
        }
        else
        {
            std::cerr << "ReplayHandTrackerImpl: right hand data not found" << std::endl;
            right_tracked_.data.reset();
        }
    }
}

} // namespace core
