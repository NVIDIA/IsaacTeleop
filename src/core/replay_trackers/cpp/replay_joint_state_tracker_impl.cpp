// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "replay_joint_state_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/joint_state_bfbs_generated.h>
#include <schema/timestamp_generated.h>

#include <iostream>
#include <string>
#include <utility>
#include <vector>

namespace core
{

// ============================================================================
// ReplayJointStateTrackerImpl
// ============================================================================

ReplayJointStateTrackerImpl::ReplayJointStateTrackerImpl(std::unique_ptr<mcap::McapReader> reader,
                                                         std::string_view base_name)
    : mcap_viewers_(std::make_unique<JointStateMcapViewers>(
          std::move(reader),
          base_name,
          std::vector<std::string>(
              JointStateRecordingTraits::replay_channels.begin(), JointStateRecordingTraits::replay_channels.end())))
{
}

const JointStateOutputTrackedT& ReplayJointStateTrackerImpl::get_data() const
{
    return tracked_;
}

void ReplayJointStateTrackerImpl::update(int64_t /*monotonic_time_ns*/)
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
            std::cerr << "ReplayJointStateTrackerImpl: joint state data not found" << std::endl;
            warned_no_data_ = true;
        }
        tracked_.data.reset();
    }
}

} // namespace core
