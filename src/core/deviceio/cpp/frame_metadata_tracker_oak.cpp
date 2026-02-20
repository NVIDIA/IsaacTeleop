// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/frame_metadata_tracker_oak.hpp"

#include "inc/deviceio/deviceio_session.hpp"

#include <flatbuffers/flatbuffers.h>
#include <schema/oak_bfbs_generated.h>

#include <vector>

namespace core
{

// ============================================================================
// FrameMetadataTrackerOak::Impl
// ============================================================================

class FrameMetadataTrackerOak::Impl : public ITrackerImpl
{
public:
    Impl(const OpenXRSessionHandles& handles, SchemaTrackerConfig config) : m_schema_reader(handles, std::move(config))
    {
    }

    bool update(XrTime /* time */) override
    {
        m_pending_records.clear();

        std::vector<SchemaTracker::SampleResult> raw_samples;
        m_schema_reader.read_all_samples(raw_samples);

        for (auto& sample : raw_samples)
        {
            auto fb = flatbuffers::GetRoot<FrameMetadata>(sample.buffer.data());
            if (fb)
            {
                FrameMetadataT parsed;
                fb->UnPackTo(&parsed);
                m_pending_records.push_back({ std::move(parsed), sample.timestamp });
            }
        }

        if (!m_pending_records.empty())
        {
            m_data = m_pending_records.back().data;
            m_last_timestamp = m_pending_records.back().timestamp;
        }

        return true;
    }

    DeviceDataTimestamp serialize(flatbuffers::FlatBufferBuilder& builder, size_t /* channel_index */) const override
    {
        auto data_offset = FrameMetadata::Pack(builder, &m_data);

        FrameMetadataRecordBuilder record_builder(builder);
        record_builder.add_data(data_offset);
        record_builder.add_timestamp(&m_last_timestamp);
        builder.Finish(record_builder.Finish());

        return m_last_timestamp;
    }

    void serialize_all(size_t /* channel_index */, const RecordCallback& callback) const override
    {
        for (const auto& record : m_pending_records)
        {
            flatbuffers::FlatBufferBuilder builder(256);
            auto data_offset = FrameMetadata::Pack(builder, &record.data);

            FrameMetadataRecordBuilder record_builder(builder);
            record_builder.add_data(data_offset);
            record_builder.add_timestamp(&record.timestamp);
            builder.Finish(record_builder.Finish());

            callback(record.timestamp, builder.GetBufferPointer(), builder.GetSize());
        }
    }

    const FrameMetadataT& get_data() const
    {
        return m_data;
    }

private:
    struct PendingRecord
    {
        FrameMetadataT data;
        DeviceDataTimestamp timestamp;
    };

    SchemaTracker m_schema_reader;
    FrameMetadataT m_data;
    DeviceDataTimestamp m_last_timestamp{};
    std::vector<PendingRecord> m_pending_records;
};

// ============================================================================
// FrameMetadataTrackerOak
// ============================================================================

FrameMetadataTrackerOak::FrameMetadataTrackerOak(const std::string& collection_id, size_t max_flatbuffer_size)
    : m_config{ .collection_id = collection_id,
                .max_flatbuffer_size = max_flatbuffer_size,
                .tensor_identifier = "frame_metadata",
                .localized_name = "FrameMetadataTrackerOak" }
{
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
    return "core.FrameMetadataRecord";
}

std::string_view FrameMetadataTrackerOak::get_schema_text() const
{
    return std::string_view(reinterpret_cast<const char*>(FrameMetadataRecordBinarySchema::data()),
                            FrameMetadataRecordBinarySchema::size());
}

std::vector<std::string> FrameMetadataTrackerOak::get_record_channels() const
{
    return { "frame_metadata" };
}

const SchemaTrackerConfig& FrameMetadataTrackerOak::get_config() const
{
    return m_config;
}

const FrameMetadataT& FrameMetadataTrackerOak::get_data(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_data();
}

std::shared_ptr<ITrackerImpl> FrameMetadataTrackerOak::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<Impl>(handles, get_config());
}

} // namespace core
