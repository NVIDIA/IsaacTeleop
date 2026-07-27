// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_oglo_tactile_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/oglo_tactile_bfbs_generated.h>

namespace core
{

namespace
{

SchemaTrackerConfig make_oglo_tensor_config(const OgloTactileTracker* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    cfg.tensor_identifier = "oglo_tactile";
    cfg.localized_name = "OgloTactileTracker";
    return cfg;
}

} // namespace

// ============================================================================
// LiveOgloTactileTrackerImpl
// ============================================================================

std::unique_ptr<OgloMcapChannels> LiveOgloTactileTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                   std::string_view base_name)
{
    return std::make_unique<OgloMcapChannels>(writer, base_name, OgloRecordingTraits::schema_name,
                                              std::vector<std::string>(OgloRecordingTraits::recording_channels.begin(),
                                                                       OgloRecordingTraits::recording_channels.end()));
}

LiveOgloTactileTrackerImpl::LiveOgloTactileTrackerImpl(const OpenXRSessionHandles& handles,
                                                       const OgloTactileTracker* tracker,
                                                       std::unique_ptr<OgloMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      m_schema_reader(handles,
                      make_oglo_tensor_config(tracker),
                      mcap_channels_.get(),
                      /*mcap_channel_index=*/0,
                      /*mcap_channel_tracked_index=*/1)
{
}

void LiveOgloTactileTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    // SchemaTracker throws on critical OpenXR/tensor failures; missing collection
    // and "no new data" are non-fatal.
    m_schema_reader.update(m_tracked.data);
}

const OgloGloveSampleTrackedT& LiveOgloTactileTrackerImpl::get_data() const
{
    return m_tracked;
}

} // namespace core
