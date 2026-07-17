// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_se3_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/se3_tracker_bfbs_generated.h>
#include <schema/timestamp_generated.h>

#include <iostream>
#include <string>
#include <utility>
#include <vector>

namespace core
{

// ============================================================================
// ReplaySe3TrackerImpl
// ============================================================================

ReplaySe3TrackerImpl::ReplaySe3TrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name)
    : mcap_viewers_(std::make_unique<Se3TrackerMcapViewers>(
          std::move(reader),
          base_name,
          std::vector<std::string>(
              Se3TrackerRecordingTraits::replay_channels.begin(), Se3TrackerRecordingTraits::replay_channels.end()))),
      no_data_message_("ReplaySe3TrackerImpl[" + std::string(base_name) + "]: no data (EOF or gap)")
{
}

const Se3TrackerPoseTrackedT& ReplaySe3TrackerImpl::get_data() const
{
    return tracked_;
}

void ReplaySe3TrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    auto record = mcap_viewers_->read(0);
    if (record)
    {
        tracked_.data = std::move(record->data);
        warned_no_data_ = false;
    }
    else
    {
        // EOF / sparse streams call this every frame; log once per gap, not per frame.
        if (!warned_no_data_)
        {
            std::cerr << no_data_message_ << std::endl;
            warned_no_data_ = true;
        }
        tracked_.data.reset();
    }
}

} // namespace core
