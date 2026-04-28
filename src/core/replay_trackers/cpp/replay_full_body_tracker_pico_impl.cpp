// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_full_body_tracker_pico_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/full_body_bfbs_generated.h>
#include <schema/timestamp_generated.h>

#include <cassert>
#include <cstring>
#include <iostream>

namespace core
{

// ============================================================================
// ReplayFullBodyTrackerPicoImpl
// ============================================================================

ReplayFullBodyTrackerPicoImpl::ReplayFullBodyTrackerPicoImpl(std::unique_ptr<mcap::McapReader> reader,
                                                             std::string_view base_name)
    : mcap_viewers_(std::make_unique<FullBodyMcapViewers>(
          std::move(reader),
          base_name,
          std::vector<std::string>(FullBodyPicoRecordingTraits::replay_channels.begin(),
                                   FullBodyPicoRecordingTraits::replay_channels.end())))
{
}

const FullBodyPosePicoTrackedT& ReplayFullBodyTrackerPicoImpl::get_body_pose() const
{
    return tracked_;
}

void ReplayFullBodyTrackerPicoImpl::update(int64_t /*monotonic_time_ns*/)
{
    auto record = mcap_viewers_->read(0);
    if (record)
    {
        tracked_.data = std::move(record->data);
    }
    else
    {
        std::cerr << "ReplayFullBodyTrackerPicoImpl: body data not found" << std::endl;
        tracked_.data.reset();
    }
}

} // namespace core
