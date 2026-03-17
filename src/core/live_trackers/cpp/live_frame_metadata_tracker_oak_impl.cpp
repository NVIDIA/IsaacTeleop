// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_frame_metadata_tracker_oak_impl.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr_utils/oxr_time.hpp>
#include <schema/oak_generated.h>

#include <stdexcept>
#include <utility>
#include <vector>

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

LiveFrameMetadataTrackerOakImpl::LiveFrameMetadataTrackerOakImpl(const OpenXRSessionHandles& handles,
                                                                 const FrameMetadataTrackerOak* tracker)
    : m_time_converter_(handles)
{
    auto configs = make_oak_tensor_configs(tracker);
    for (auto& config : configs)
    {
        StreamState state;
        state.reader = std::make_unique<SchemaTracker>(handles, std::move(config));
        m_streams.push_back(std::move(state));
    }
}

bool LiveFrameMetadataTrackerOakImpl::update(XrTime time)
{
    m_last_update_time_ = time;
    for (auto& stream : m_streams)
    {
        stream.pending_records.clear();
        stream.collection_present = stream.reader->read_all_samples(stream.pending_records);

        if (!stream.collection_present)
        {
            stream.tracked.data.reset();
            continue;
        }

        // When present but empty, intentionally retain the last sample in stream.tracked.data
        if (!stream.pending_records.empty())
        {
            auto fb = flatbuffers::GetRoot<FrameMetadataOak>(stream.pending_records.back().buffer.data());
            if (fb)
            {
                if (!stream.tracked.data)
                {
                    stream.tracked.data = std::make_shared<FrameMetadataOakT>();
                }
                fb->UnPackTo(stream.tracked.data.get());
            }
        }
    }

    return true;
}

void LiveFrameMetadataTrackerOakImpl::serialize_all(size_t channel_index, const RecordCallback& callback) const
{
    if (channel_index >= m_streams.size())
    {
        throw std::runtime_error("FrameMetadataTrackerOak::serialize_all: invalid channel_index " +
                                 std::to_string(channel_index) + " (have " + std::to_string(m_streams.size()) +
                                 " streams)");
    }

    int64_t update_ns = m_time_converter_.convert_xrtime_to_monotonic_ns(m_last_update_time_);

    const auto& stream = m_streams[channel_index];
    if (stream.pending_records.empty())
    {
        if (!stream.collection_present)
        {
            DeviceDataTimestamp update_timestamp(update_ns, update_ns, 0);
            flatbuffers::FlatBufferBuilder builder(64);
            FrameMetadataOakRecordBuilder record_builder(builder);
            record_builder.add_timestamp(&update_timestamp);
            builder.Finish(record_builder.Finish());
            callback(update_ns, builder.GetBufferPointer(), builder.GetSize());
        }
        return;
    }
    const auto& pending = stream.pending_records;

    for (const auto& sample : pending)
    {
        auto fb = flatbuffers::GetRoot<FrameMetadataOak>(sample.buffer.data());
        if (!fb)
        {
            continue;
        }

        FrameMetadataOakT parsed;
        fb->UnPackTo(&parsed);

        flatbuffers::FlatBufferBuilder builder(256);
        auto data_offset = FrameMetadataOak::Pack(builder, &parsed);
        FrameMetadataOakRecordBuilder record_builder(builder);
        record_builder.add_data(data_offset);
        record_builder.add_timestamp(&sample.timestamp);
        builder.Finish(record_builder.Finish());
        callback(update_ns, builder.GetBufferPointer(), builder.GetSize());
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
