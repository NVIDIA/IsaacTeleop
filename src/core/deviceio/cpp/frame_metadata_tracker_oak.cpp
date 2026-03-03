// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/frame_metadata_tracker_oak.hpp"

#include "inc/deviceio/deviceio_session.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr_utils/oxr_time.hpp>
#include <schema/oak_bfbs_generated.h>

#include <stdexcept>
#include <vector>

namespace core
{

// ============================================================================
// FrameMetadataTrackerOak::Impl
// ============================================================================

FrameMetadataTrackerOak::Impl::Impl(const OpenXRSessionHandles& handles, std::vector<SchemaTrackerConfig> configs)
    : m_time_converter_(handles)
{
    for (auto& config : configs)
    {
        StreamState state;
        state.reader = std::make_unique<SchemaTracker>(handles, std::move(config));
        m_streams.push_back(std::move(state));
    }
}

bool FrameMetadataTrackerOak::Impl::update(XrTime time)
{
    m_last_update_time_ = time;
    for (auto& stream : m_streams)
    {
        stream.pending_records.clear();
        stream.collection_present = stream.reader->read_all_samples(stream.pending_records);

        if (!stream.collection_present)
        {
            // Device disappeared: clear tracked data so get_stream_data() reflects absence.
            stream.tracked.data.reset();
            continue;
        }

        // Deserialize only the last sample to keep stream.tracked current for get_stream_data().
        // Full per-sample deserialization is deferred to serialize_all().
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
        // When no samples arrive but the collection is present, stream.tracked retains
        // the last seen value so get_stream_data() reflects the most recently received state.
    }

    return true;
}

void FrameMetadataTrackerOak::Impl::serialize_all(size_t channel_index, const RecordCallback& callback) const
{
    if (channel_index >= m_streams.size())
    {
        throw std::runtime_error("FrameMetadataTrackerOak::serialize_all: invalid channel_index " +
                                 std::to_string(channel_index) + " (have " + std::to_string(m_streams.size()) +
                                 " streams)");
    }

    // The FlatBufferBuilder is stack-allocated per record. The data pointer
    // passed to the callback is only valid for the duration of that callback
    // invocation — the caller must not retain it after returning.
    //
    // The DeviceDataTimestamp passed to the callback is the update-tick time
    // (used by the MCAP recorder for logTime/publishTime). The timestamps
    // embedded inside the Record payload are the tensor transport timestamps.
    int64_t update_ns = m_time_converter_.convert_xrtime_to_monotonic_ns(m_last_update_time_);

    const auto& stream = m_streams[channel_index];
    if (stream.pending_records.empty())
    {
        if (!stream.collection_present)
        {
            // Device disappeared: emit one empty record to mark the absence in the MCAP stream.
            // The heartbeat carries the update-tick time in both the payload and the log timestamp.
            DeviceDataTimestamp update_timestamp(update_ns, 0, 0);
            flatbuffers::FlatBufferBuilder builder(64);
            FrameMetadataOakRecordBuilder record_builder(builder);
            record_builder.add_timestamp(&update_timestamp);
            builder.Finish(record_builder.Finish());
            callback(update_ns, builder.GetBufferPointer(), builder.GetSize());
        }
        // If the collection is present but no new samples arrived this tick, emit nothing.
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

const FrameMetadataOakTrackedT& FrameMetadataTrackerOak::Impl::get_stream_data(size_t stream_index) const
{
    if (stream_index >= m_streams.size())
    {
        throw std::runtime_error("FrameMetadataTrackerOak::get_stream_data: invalid stream_index " +
                                 std::to_string(stream_index) + " (have " + std::to_string(m_streams.size()) +
                                 " streams)");
    }
    return m_streams[stream_index].tracked;
}

// ============================================================================
// FrameMetadataTrackerOak
// ============================================================================

FrameMetadataTrackerOak::FrameMetadataTrackerOak(const std::string& collection_prefix,
                                                 const std::vector<StreamType>& streams,
                                                 size_t max_flatbuffer_size)
{
    if (streams.empty())
    {
        throw std::runtime_error("FrameMetadataTrackerOak: at least one stream is required");
    }

    for (auto type : streams)
    {
        const char* name = EnumNameStreamType(type);
        m_configs.push_back({ .collection_id = collection_prefix + "/" + name,
                              .max_flatbuffer_size = max_flatbuffer_size,
                              .tensor_identifier = "frame_metadata",
                              .localized_name = std::string("FrameMetadataTracker_") + name });
        m_channel_names.emplace_back(name);
    }
}

std::vector<std::string> FrameMetadataTrackerOak::get_required_extensions() const
{
    return SchemaTracker::get_required_extensions();
}

std::string_view FrameMetadataTrackerOak::get_name() const
{
    return "FrameMetadataTrackerOak";
}

std::string_view FrameMetadataTrackerOak::get_schema_name() const
{
    return "core.FrameMetadataOakRecord";
}

std::string_view FrameMetadataTrackerOak::get_schema_text() const
{
    return std::string_view(reinterpret_cast<const char*>(FrameMetadataOakRecordBinarySchema::data()),
                            FrameMetadataOakRecordBinarySchema::size());
}

const FrameMetadataOakTrackedT& FrameMetadataTrackerOak::get_stream_data(const DeviceIOSession& session,
                                                                         size_t stream_index) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_stream_data(stream_index);
}

std::shared_ptr<ITrackerImpl> FrameMetadataTrackerOak::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<Impl>(handles, m_configs);
}

} // namespace core
