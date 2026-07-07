// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_joint_state_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/joint_state_bfbs_generated.h>

namespace core
{

namespace
{

SchemaTrackerConfig make_joint_state_tensor_config(const JointStateTracker* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    cfg.tensor_identifier = "joint_state";
    cfg.localized_name = "JointStateTracker";
    return cfg;
}

} // namespace

// ============================================================================
// LiveJointStateTrackerImpl
// ============================================================================

std::unique_ptr<JointStateMcapChannels> LiveJointStateTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                        std::string_view base_name)
{
    return std::make_unique<JointStateMcapChannels>(
        writer, base_name, JointStateRecordingTraits::schema_name,
        std::vector<std::string>(JointStateRecordingTraits::recording_channels.begin(),
                                 JointStateRecordingTraits::recording_channels.end()));
}

LiveJointStateTrackerImpl::LiveJointStateTrackerImpl(const OpenXRSessionHandles& handles,
                                                     const JointStateTracker* tracker,
                                                     std::unique_ptr<JointStateMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      m_schema_reader(handles,
                      make_joint_state_tensor_config(tracker),
                      mcap_channels_.get(),
                      /*mcap_channel_index=*/0,
                      /*mcap_channel_tracked_index=*/1)
{
}

void LiveJointStateTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    // Policy: SchemaTracker throws on critical OpenXR/tensor API failures.
    // Missing collection/no new data are treated as common non-fatal cases.
    m_schema_reader.update(m_tracked.data);
}

const JointStateOutputTrackedT& LiveJointStateTrackerImpl::get_data() const
{
    return m_tracked;
}

} // namespace core
