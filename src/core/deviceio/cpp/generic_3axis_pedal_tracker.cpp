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
        SampleResult sample;
        if (m_schema_reader.read_sample(sample))
        {
            auto fb = flatbuffers::GetRoot<Generic3AxisPedalOutput>(sample.buffer.data());
            if (fb)
            {
                if (!m_tracked.data)
                {
                    m_tracked.data = std::make_shared<Generic3AxisPedalOutputT>();
                }
                fb->UnPackTo(m_tracked.data.get());
                m_last_timestamp = sample.timestamp;
                return true;
            }
        }
        m_tracked.data.reset();
        return true;
    }

    DeviceDataTimestamp serialize(flatbuffers::FlatBufferBuilder& builder, size_t /*channel_index*/ = 0) const override
    {
        Generic3AxisPedalOutputRecordBuilder record_builder(builder);
        if (m_tracked.data)
        {
            auto data_offset = Generic3AxisPedalOutput::Pack(builder, m_tracked.data.get());
            record_builder.add_data(data_offset);
        }
        record_builder.add_timestamp(&m_last_timestamp);
        builder.Finish(record_builder.Finish());
        return m_last_timestamp;
    }

    const Generic3AxisPedalOutputTrackedT& get_data() const
    {
        return m_tracked;
    }

private:
    SchemaTracker m_schema_reader;
    Generic3AxisPedalOutputTrackedT m_tracked;
    DeviceDataTimestamp m_last_timestamp{};
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

const SchemaTrackerConfig& Generic3AxisPedalTracker::get_config() const
{
    return m_config;
}

const Generic3AxisPedalOutputTrackedT& Generic3AxisPedalTracker::get_data(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_data();
}

std::shared_ptr<ITrackerImpl> Generic3AxisPedalTracker::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<Impl>(handles, get_config());
}

} // namespace core
