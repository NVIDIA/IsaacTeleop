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

ReplayHandTrackerImpl::ReplayHandTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name)
    : mcap_viewers_(
          std::make_unique<HandMcapViewers>(std::move(reader),
                                            base_name,
                                            std::vector<std::string>(HandRecordingTraits::replay_channels.begin(),
                                                                     HandRecordingTraits::replay_channels.end())))
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
    auto left_record = mcap_viewers_->read(0);
    auto right_record = mcap_viewers_->read(1);
    if (left_record)
    {
        left_tracked_.data = std::move(left_record->data);
    }
    else
    {
        std::cerr << "ReplayHandTrackerImpl: left hand data not found" << std::endl;
        left_tracked_.data.reset();
    }

    if (right_record)
    {
        right_tracked_.data = std::move(right_record->data);
    }
    else
    {
        std::cerr << "ReplayHandTrackerImpl: right hand data not found" << std::endl;
        right_tracked_.data.reset();
    }
}

} // namespace core
