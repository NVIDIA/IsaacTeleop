// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_frame_metadata_tracker_oak_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/oak_bfbs_generated.h>

#include <utility>

namespace core
{

namespace
{

SchemaTrackerConfig make_frame_metadata_oak_tensor_config(const FrameMetadataTrackerOak* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    cfg.tensor_identifier = "frame_metadata";
    cfg.localized_name = "FrameMetadataTrackerOak";
    return cfg;
}

} // namespace

// ============================================================================
// LiveFrameMetadataTrackerOakImpl
// ============================================================================

std::unique_ptr<OakMcapChannels> LiveFrameMetadataTrackerOakImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                       std::string_view base_name)
{
    return std::make_unique<OakMcapChannels>(writer, base_name, OakRecordingTraits::schema_name,
                                             std::vector<std::string>(OakRecordingTraits::recording_channels.begin(),
                                                                      OakRecordingTraits::recording_channels.end()));
}

LiveFrameMetadataTrackerOakImpl::LiveFrameMetadataTrackerOakImpl(const OpenXRSessionHandles& handles,
                                                                 const FrameMetadataTrackerOak* tracker,
                                                                 std::unique_ptr<OakMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      m_schema_reader(handles, make_frame_metadata_oak_tensor_config(tracker), mcap_channels_.get(), 0, 1)
{
    // No-op: members set in the initializer list.
}

void LiveFrameMetadataTrackerOakImpl::update(int64_t /*monotonic_time_ns*/)
{
    // Policy: SchemaTracker throws on critical OpenXR/tensor API failures. Missing
    // stream collection / no fresh sample are treated as common non-fatal cases.
    m_schema_reader.update(m_tracked.data);
}

const FrameMetadataOakTrackedT& LiveFrameMetadataTrackerOakImpl::get_data() const
{
    return m_tracked;
}

} // namespace core
