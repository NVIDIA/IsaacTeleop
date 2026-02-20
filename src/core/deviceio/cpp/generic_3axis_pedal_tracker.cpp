// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/generic_3axis_pedal_tracker.hpp"

#include "inc/deviceio/deviceio_session.hpp"

#include <flatbuffers/flatbuffers.h>

#include <vector>

namespace core
{

// ============================================================================
// Generic3AxisPedalTracker::Impl
// ============================================================================

class Generic3AxisPedalTracker::Impl : public ITrackerImpl
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
            auto fb = flatbuffers::GetRoot<Generic3AxisPedalOutput>(sample.buffer.data());
            if (fb)
            {
                Generic3AxisPedalOutputT parsed;
                fb->UnPackTo(&parsed);
                m_pending_records.push_back({ std::move(parsed), sample.timestamp });
            }
        }

        if (!m_pending_records.empty())
        {
            m_data = m_pending_records.back().data;
            m_last_timestamp = m_pending_records.back().timestamp;
        }
        else
        {
            m_data.is_valid = false;
        }

        return true;
    }

    DeviceDataTimestamp serialize(flatbuffers::FlatBufferBuilder& builder, size_t /* channel_index */) const override
    {
        auto data_offset = Generic3AxisPedalOutput::Pack(builder, &m_data);

        Generic3AxisPedalOutputRecordBuilder record_builder(builder);
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
            auto data_offset = Generic3AxisPedalOutput::Pack(builder, &record.data);

            Generic3AxisPedalOutputRecordBuilder record_builder(builder);
            record_builder.add_data(data_offset);
            record_builder.add_timestamp(&record.timestamp);
            builder.Finish(record_builder.Finish());

            callback(record.timestamp, builder.GetBufferPointer(), builder.GetSize());
        }
    }

    const Generic3AxisPedalOutputT& get_data() const
    {
        return m_data;
    }

private:
    struct PendingRecord
    {
        Generic3AxisPedalOutputT data;
        DeviceDataTimestamp timestamp;
    };

    SchemaTracker m_schema_reader;
    Generic3AxisPedalOutputT m_data;
    DeviceDataTimestamp m_last_timestamp{};
    std::vector<PendingRecord> m_pending_records;
};

// ============================================================================
// Generic3AxisPedalTracker
// ============================================================================

Generic3AxisPedalTracker::Generic3AxisPedalTracker(const std::string& collection_id, size_t max_flatbuffer_size)
    : m_config{ .collection_id = collection_id,
                .max_flatbuffer_size = max_flatbuffer_size,
                .tensor_identifier = "generic_3axis_pedal",
                .localized_name = "Generic3AxisPedalTracker" }
{
}

std::vector<std::string> Generic3AxisPedalTracker::get_required_extensions() const
{
    return SchemaTracker::get_required_extensions();
}

std::string_view Generic3AxisPedalTracker::get_name() const
{
    return "Generic3AxisPedalTracker";
}

std::string_view Generic3AxisPedalTracker::get_schema_name() const
{
    return "core.Generic3AxisPedalOutputRecord";
}

std::string_view Generic3AxisPedalTracker::get_schema_text() const
{
    return std::string_view(reinterpret_cast<const char*>(Generic3AxisPedalOutputRecordBinarySchema::data()),
                            Generic3AxisPedalOutputRecordBinarySchema::size());
}

std::vector<std::string> Generic3AxisPedalTracker::get_record_channels() const
{
    return { "generic_3axis_pedal" };
}

const SchemaTrackerConfig& Generic3AxisPedalTracker::get_config() const
{
    return m_config;
}

const Generic3AxisPedalOutputT& Generic3AxisPedalTracker::get_data(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_data();
}

std::shared_ptr<ITrackerImpl> Generic3AxisPedalTracker::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<Impl>(handles, get_config());
}

} // namespace core
