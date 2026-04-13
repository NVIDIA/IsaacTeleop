// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_generic_3axis_pedal_tracker_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/pedals_bfbs_generated.h>

namespace core
{

namespace
{

SchemaTrackerConfig make_pedal_tensor_config(const Generic3AxisPedalTracker* tracker)
{
    SchemaTrackerConfig cfg;
    cfg.collection_id = tracker->collection_id();
    cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
    cfg.tensor_identifier = "generic_3axis_pedal";
    cfg.localized_name = "Generic3AxisPedalTracker";
    return cfg;
}

} // namespace

// ============================================================================
// LiveGeneric3AxisPedalTrackerImpl
// ============================================================================

std::unique_ptr<PedalMcapChannels> LiveGeneric3AxisPedalTrackerImpl::create_mcap_channels(mcap::McapWriter& writer,
                                                                                          std::string_view base_name)
{
    return std::make_unique<PedalMcapChannels>(
        writer, base_name, PedalRecordingTraits::schema_name,
        std::vector<std::string>(PedalRecordingTraits::channels.begin(), PedalRecordingTraits::channels.end()));
}

LiveGeneric3AxisPedalTrackerImpl::LiveGeneric3AxisPedalTrackerImpl(const OpenXRSessionHandles& handles,
                                                                   const Generic3AxisPedalTracker* tracker,
                                                                   std::unique_ptr<PedalMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels)),
      m_schema_reader(handles, make_pedal_tensor_config(tracker), mcap_channels_.get(), 0, 1)
{
}

void LiveGeneric3AxisPedalTrackerImpl::update(int64_t /*monotonic_time_ns*/)
{
    // Policy: SchemaTracker throws on critical OpenXR/tensor API failures.
    // Missing collection/no new data are treated as common non-fatal cases.
    m_schema_reader.update(m_tracked.data);
}

const Generic3AxisPedalOutputTrackedT& LiveGeneric3AxisPedalTrackerImpl::get_data() const
{
    return m_tracked;
}

} // namespace core
