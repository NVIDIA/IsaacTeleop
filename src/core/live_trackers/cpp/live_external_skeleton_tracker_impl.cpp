// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_external_skeleton_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/external_skeleton_bfbs_generated.h>

namespace core
{

namespace
{

SchemaTrackerConfig make_external_skeleton_tensor_config(const ExternalSkeletonTracker* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    cfg.tensor_identifier = "external_skeleton_pose";
    cfg.localized_name = "ExternalSkeletonTracker";
    return cfg;
}

} // namespace

// ============================================================================
// LiveExternalSkeletonTrackerImpl
// ============================================================================

std::unique_ptr<ExternalSkeletonMcapChannels> LiveExternalSkeletonTrackerImpl::create_mcap_channels(
    mcap::McapWriter& writer, std::string_view base_name)
{
    return std::make_unique<ExternalSkeletonMcapChannels>(
        writer, base_name, ExternalSkeletonRecordingTraits::schema_name,
        std::vector<std::string>(ExternalSkeletonRecordingTraits::recording_channels.begin(),
                                 ExternalSkeletonRecordingTraits::recording_channels.end()));
}

LiveExternalSkeletonTrackerImpl::LiveExternalSkeletonTrackerImpl(
    const OpenXRSessionHandles& handles,
    const ExternalSkeletonTracker* tracker,
    std::unique_ptr<ExternalSkeletonMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      m_schema_reader(handles,
                      make_external_skeleton_tensor_config(tracker),
                      mcap_channels_.get(),
                      /*mcap_channel_index=*/0,
                      /*mcap_channel_tracked_index=*/1)
{
}

void LiveExternalSkeletonTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    // SchemaTracker handles timestamp conversion (monotonic ns ↔ XrTime) and
    // MCAP write internally; missing collection / no new samples are non-fatal.
    m_schema_reader.update(m_tracked.data);
}

const ExternalSkeletonPoseTrackedT& LiveExternalSkeletonTrackerImpl::get_skeleton_pose() const
{
    return m_tracked;
}

} // namespace core
