// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_full_body_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/full_body_bfbs_generated.h>
#include <schema/serialized.hpp>
#include <schema/timestamp_generated.h>

#include <cassert>
#include <cstring>

namespace core
{

// ============================================================================
// ReplayFullBodyTrackerImpl
// ============================================================================

ReplayFullBodyTrackerImpl::ReplayFullBodyTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                                                     std::string_view base_name,
                                                     const RecordedSchemas& recorded)
    : mcap_viewers_(std::make_unique<FullBodyMcapViewers>(
          std::move(reader),
          base_name,
          std::vector<std::string>(
              FullBodyRecordingTraits::replay_channels.begin(), FullBodyRecordingTraits::replay_channels.end()),
          recorded)),
      logger_(isaacteleop::Logger::get("isaacteleop.core.ReplayFullBodyTrackerImpl"))
{
}

const Serialized<FullBodyPose>& ReplayFullBodyTrackerImpl::get_body_pose() const
{
    return tracked_;
}

void ReplayFullBodyTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    auto record = mcap_viewers_->read(0);
    if (record)
    {
        tracked_ = record.narrow(record->data());
        warned_no_data_ = false;
    }
    else
    {
        if (!warned_no_data_)
        {
            logger_->warn("body data not found");
            warned_no_data_ = true;
        }
        tracked_.reset();
    }
}

} // namespace core
