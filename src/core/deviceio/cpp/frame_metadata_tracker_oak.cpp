// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/frame_metadata_tracker_oak.hpp"

#include "inc/deviceio/deviceio_session.hpp"

#include <flatbuffers/flatbuffers.h>
#include <schema/oak_bfbs_generated.h>

#include <stdexcept>
#include <vector>

namespace core
{

// ============================================================================
// FrameMetadataTrackerOak::Impl
// ============================================================================

class FrameMetadataTrackerOak::Impl : public ITrackerImpl
{
public:
    struct StreamState
    {
        std::unique_ptr<SchemaTracker> reader;
        FrameMetadataOakT data;
        DeviceDataTimestamp last_timestamp{};
    };

    Impl(const OpenXRSessionHandles& handles, std::vector<SchemaTrackerConfig> configs)
    {
        for (auto& config : configs)
        {
            StreamState state;
            state.reader = std::make_unique<SchemaTracker>(handles, std::move(config));
            m_streams.push_back(std::move(state));
        }
    }

    bool update(XrTime /* time */) override
    {
        for (auto& stream : m_streams)
        {
            SampleResult sample;
            if (stream.reader->read_sample(sample))
            {
                auto fb = flatbuffers::GetRoot<FrameMetadataOak>(sample.buffer.data());
                if (fb)
                {
                    fb->UnPackTo(&stream.data);
                    stream.last_timestamp = sample.timestamp;
                }
            }
        }

        return true;
    }

    DeviceDataTimestamp serialize(flatbuffers::FlatBufferBuilder& builder, size_t channel_index) const override
    {
        if (channel_index >= m_streams.size())
        {
            throw std::runtime_error("FrameMetadataTrackerOak::serialize: invalid channel_index " +
                                     std::to_string(channel_index) + " (have " + std::to_string(m_streams.size()) +
                                     " streams)");
        }

        const auto& stream = m_streams[channel_index];
        auto data_offset = FrameMetadataOak::Pack(builder, &stream.data);

        FrameMetadataOakRecordBuilder record_builder(builder);
        record_builder.add_data(data_offset);
        record_builder.add_timestamp(&stream.last_timestamp);
        builder.Finish(record_builder.Finish());

        return stream.last_timestamp;
    }

    const FrameMetadataOakT& get_stream_data(size_t stream_index) const
    {
        if (stream_index >= m_streams.size())
        {
            throw std::runtime_error("FrameMetadataTrackerOak::get_stream_data: invalid stream_index " +
                                     std::to_string(stream_index) + " (have " + std::to_string(m_streams.size()) +
                                     " streams)");
        }
        return m_streams[stream_index].data;
    }

private:
    std::vector<StreamState> m_streams;
};

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

const FrameMetadataOakT& FrameMetadataTrackerOak::get_stream_data(const DeviceIOSession& session, size_t stream_index) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_stream_data(stream_index);
}

std::shared_ptr<ITrackerImpl> FrameMetadataTrackerOak::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<Impl>(handles, m_configs);
}

} // namespace core
