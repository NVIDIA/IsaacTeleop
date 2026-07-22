// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_full_body_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/full_body_bfbs_generated.h>
#include <schema/timestamp_generated.h>

#include <cassert>
#include <cstring>
#include <iostream>

namespace core
{

// ============================================================================
// ReplayFullBodyTrackerImpl
// ============================================================================

ReplayFullBodyTrackerImpl::ReplayFullBodyTrackerImpl(std::unique_ptr<mcap::McapReader> reader, std::string_view base_name)
    : mcap_viewers_(std::make_unique<FullBodyMcapViewers>(
          std::move(reader),
          base_name,
          std::vector<std::string>(
              FullBodyRecordingTraits::replay_channels.begin(), FullBodyRecordingTraits::replay_channels.end())))
{
}

const FullBodyPoseTrackedT& ReplayFullBodyTrackerImpl::get_body_pose() const
{
    return tracked_;
}

void ReplayFullBodyTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    auto record = mcap_viewers_->read(0);
    if (record)
    {
        tracked_.data = std::move(record->data);
    }
    else
    {
        std::cerr << "ReplayFullBodyTrackerImpl: body data not found" << std::endl;
        tracked_.data.reset();
    }
}

} // namespace core
