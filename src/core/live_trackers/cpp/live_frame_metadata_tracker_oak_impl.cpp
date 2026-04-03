// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_frame_metadata_tracker_oak_impl.hpp"

#include <mcap/recording_traits.hpp>
#include <schema/oak_bfbs_generated.h>

#include <stdexcept>
#include <utility>

namespace core
{

namespace
{

std::vector<SchemaTrackerConfig> make_oak_tensor_configs(const FrameMetadataTrackerOak* tracker)
{
    std::vector<SchemaTrackerConfig> configs;
    configs.reserve(tracker->streams().size());
    for (auto type : tracker->streams())
    {
        const char* name = EnumNameStreamType(type);
        SchemaTrackerConfig cfg;
        cfg.collection_id = tracker->collection_prefix() + "/" + name;
        cfg.max_flatbuffer_size = tracker->max_flatbuffer_size();
        cfg.tensor_identifier = "frame_metadata";
        cfg.localized_name = std::string("FrameMetadataTracker_") + name;
        configs.push_back(std::move(cfg));
    }
    return configs;
}

} // namespace

// ============================================================================
// LiveFrameMetadataTrackerOakImpl
// ============================================================================

std::unique_ptr<OakMcapChannels> LiveFrameMetadataTrackerOakImpl::create_mcap_channels(
    mcap::McapWriter& writer, std::string_view base_name, const FrameMetadataTrackerOak* tracker)
{
    return std::make_unique<OakMcapChannels>(
        writer, base_name, OakRecordingTraits::schema_name, tracker->get_stream_names());
}

LiveFrameMetadataTrackerOakImpl::LiveFrameMetadataTrackerOakImpl(const OpenXRSessionHandles& handles,
                                                                 const FrameMetadataTrackerOak* tracker,
                                                                 std::unique_ptr<OakMcapChannels> mcap_channels)
    : mcap_channels_(std::move(mcap_channels))
{
    auto configs = make_oak_tensor_configs(tracker);
    for (size_t i = 0; i < configs.size(); ++i)
    {
        StreamState state;
        state.reader = std::make_unique<OakSchemaTracker>(handles, std::move(configs[i]), mcap_channels_.get(), i);
        m_streams.push_back(std::move(state));
    }
}

void LiveFrameMetadataTrackerOakImpl::update(int64_t /*monotonic_time_ns*/)
{
    // Policy: per-stream SchemaTracker throws on critical OpenXR/tensor API failures.
    // Missing stream collection/no fresh sample are treated as common non-fatal cases.
    for (auto& stream : m_streams)
    {
        stream.reader->update(stream.tracked.data);
    }
}

const FrameMetadataOakTrackedT& LiveFrameMetadataTrackerOakImpl::get_stream_data(size_t stream_index) const
{
    if (stream_index >= m_streams.size())
    {
        throw std::runtime_error("FrameMetadataTrackerOak::get_stream_data: invalid stream_index " +
                                 std::to_string(stream_index) + " (have " + std::to_string(m_streams.size()) +
                                 " streams)");
    }
    return m_streams[stream_index].tracked;
}

} // namespace core
