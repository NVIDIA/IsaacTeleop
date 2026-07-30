// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_se3_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/se3_tracker_bfbs_generated.h>

namespace core
{

namespace
{

SchemaTrackerConfig make_se3_tracker_tensor_config(const Se3Tracker* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    // Wire rendezvous with producer plugins; single source of truth on the facade.
    cfg.tensor_identifier = std::string(Se3Tracker::TENSOR_IDENTIFIER);
    cfg.localized_name = "Se3Tracker";
    return cfg;
}

} // namespace

// ============================================================================
// LiveSe3TrackerImpl
// ============================================================================

std::unique_ptr<Se3TrackerMcapChannels> LiveSe3TrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                 std::string_view base_name)
{
    return std::make_unique<Se3TrackerMcapChannels>(
        writer, base_name, Se3TrackerRecordingTraits::schema_name,
        std::vector<std::string>(Se3TrackerRecordingTraits::recording_channels.begin(),
                                 Se3TrackerRecordingTraits::recording_channels.end()));
}

LiveSe3TrackerImpl::LiveSe3TrackerImpl(const OpenXRSessionHandles& handles,
                                       const Se3Tracker* tracker,
                                       std::unique_ptr<Se3TrackerMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      // Channel indices follow Se3TrackerRecordingTraits::recording_channels order:
      // 0 = per-sample "se3_tracker", 1 = per-tick "se3_tracker_tracked".
      m_schema_reader(handles,
                      make_se3_tracker_tensor_config(tracker),
                      mcap_channels_.get(),
                      /*mcap_channel_index=*/0,
                      /*mcap_channel_tracked_index=*/1)
{
}

void LiveSe3TrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    // Policy: SchemaTracker throws on critical OpenXR/tensor API failures.
    // Missing collection/no new data are treated as common non-fatal cases.
    m_schema_reader.update(m_tracked.data);
}

const Se3TrackerPoseTrackedT& LiveSe3TrackerImpl::get_data() const
{
    return m_tracked;
}

} // namespace core
