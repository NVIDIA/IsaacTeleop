// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_frame_metadata_tracker_oak_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/oak_bfbs_generated.h>

#include <utility>
#include <vector>

namespace core
{

namespace
{

SchemaTrackerConfig make_oak_tensor_config(const FrameMetadataTrackerOak* tracker)
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
      reader_(handles, make_oak_tensor_config(tracker), mcap_channels_.get(), /*mcap_channel_index=*/0)
{
}

void LiveFrameMetadataTrackerOakImpl::update(int64_t /*monotonic_time_ns*/)
{
    reader_.update(tracked_.data);
}

const FrameMetadataOakTrackedT& LiveFrameMetadataTrackerOakImpl::get_data() const
{
    return tracked_;
}

} // namespace core
