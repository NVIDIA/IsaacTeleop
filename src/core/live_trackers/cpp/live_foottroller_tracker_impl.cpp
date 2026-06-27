// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_foottroller_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/foottroller_bfbs_generated.h>

namespace core
{

namespace
{

SchemaTrackerConfig make_foottroller_tensor_config(const FoottrollerTracker* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    cfg.tensor_identifier = "foottroller";
    cfg.localized_name = "FoottrollerTracker";
    return cfg;
}

} // namespace

// ============================================================================
// LiveFoottrollerTrackerImpl
// ============================================================================

std::unique_ptr<FoottrollerMcapChannels> LiveFoottrollerTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                          std::string_view base_name)
{
    return std::make_unique<FoottrollerMcapChannels>(
        writer, base_name, FoottrollerRecordingTraits::schema_name,
        std::vector<std::string>(FoottrollerRecordingTraits::recording_channels.begin(),
                                 FoottrollerRecordingTraits::recording_channels.end()));
}

LiveFoottrollerTrackerImpl::LiveFoottrollerTrackerImpl(const OpenXRSessionHandles& handles,
                                                       const FoottrollerTracker* tracker,
                                                       std::unique_ptr<FoottrollerMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      m_schema_reader(handles,
                      make_foottroller_tensor_config(tracker),
                      mcap_channels_.get(),
                      /*mcap_channel_index=*/0,
                      /*mcap_channel_tracked_index=*/1)
{
}

void LiveFoottrollerTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    // Policy: SchemaTracker throws on critical OpenXR/tensor API failures.
    // Missing collection/no new data are treated as common non-fatal cases.
    m_schema_reader.update(m_tracked.data);
}

const FoottrollerOutputTrackedT& LiveFoottrollerTrackerImpl::get_data() const
{
    return m_tracked;
}

} // namespace core
