// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_spacemouse_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/spacemouse_bfbs_generated.h>

namespace core
{

namespace
{

SchemaTrackerConfig make_spacemouse_tensor_config(const SpaceMouseTracker* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    cfg.tensor_identifier = "spacemouse";
    cfg.localized_name = "SpaceMouseTracker";
    return cfg;
}

} // namespace

// ============================================================================
// LiveSpaceMouseTrackerImpl
// ============================================================================

std::unique_ptr<SpaceMouseMcapChannels> LiveSpaceMouseTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                        std::string_view base_name)
{
    return std::make_unique<SpaceMouseMcapChannels>(
        writer, base_name, SpaceMouseRecordingTraits::schema_name,
        std::vector<std::string>(SpaceMouseRecordingTraits::recording_channels.begin(),
                                 SpaceMouseRecordingTraits::recording_channels.end()));
}

LiveSpaceMouseTrackerImpl::LiveSpaceMouseTrackerImpl(const OpenXRSessionHandles& handles,
                                                     const SpaceMouseTracker* tracker,
                                                     std::unique_ptr<SpaceMouseMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      m_schema_reader(handles,
                      make_spacemouse_tensor_config(tracker),
                      mcap_channels_.get(),
                      /*mcap_channel_index=*/0,
                      /*mcap_channel_tracked_index=*/1)
{
}

void LiveSpaceMouseTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    // Policy: SchemaTracker throws on critical OpenXR/tensor API failures.
    // Missing collection/no new data are treated as common non-fatal cases.
    m_schema_reader.update(m_tracked.data);
}

const SpaceMouseOutputTrackedT& LiveSpaceMouseTrackerImpl::get_data() const
{
    return m_tracked;
}

} // namespace core
