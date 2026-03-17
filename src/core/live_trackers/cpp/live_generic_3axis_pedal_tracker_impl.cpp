// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "live_generic_3axis_pedal_tracker_impl.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr_utils/oxr_time.hpp>

#include <stdexcept>
#include <utility>
#include <vector>

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

LiveGeneric3AxisPedalTrackerImpl::LiveGeneric3AxisPedalTrackerImpl(const OpenXRSessionHandles& handles,
                                                                   const Generic3AxisPedalTracker* tracker)
    : m_schema_reader(handles, make_pedal_tensor_config(tracker)), m_time_converter_(handles)
{
}

bool LiveGeneric3AxisPedalTrackerImpl::update(XrTime time)
{
    m_last_update_time_ = time;
    m_pending_records.clear();
    m_collection_present = m_schema_reader.read_all_samples(m_pending_records);

    // Apply any samples returned by read_all_samples before treating the collection as absent.
    if (!m_pending_records.empty())
    {
        auto fb = flatbuffers::GetRoot<Generic3AxisPedalOutput>(m_pending_records.back().buffer.data());
        if (fb)
        {
            if (!m_tracked.data)
            {
                m_tracked.data = std::make_shared<Generic3AxisPedalOutputT>();
            }
            fb->UnPackTo(m_tracked.data.get());
        }
    }
    else if (!m_collection_present)
    {
        // No new samples and collection unavailable — clear last-known state.
        m_tracked.data.reset();
    }
    // When the collection exists but read_all_samples drained zero new samples, retain m_tracked.data.

    return true;
}

void LiveGeneric3AxisPedalTrackerImpl::serialize_all(size_t channel_index, const RecordCallback& callback) const
{
    if (channel_index != 0)
    {
        throw std::runtime_error("Generic3AxisPedalTracker::serialize_all: invalid channel_index " +
                                 std::to_string(channel_index) + " (only channel 0 exists)");
    }

    int64_t update_ns = m_time_converter_.convert_xrtime_to_monotonic_ns(m_last_update_time_);
    const size_t builder_capacity = m_schema_reader.config().max_flatbuffer_size;

    if (m_pending_records.empty())
    {
        if (!m_collection_present)
        {
            DeviceDataTimestamp update_timestamp(update_ns, update_ns, 0);
            flatbuffers::FlatBufferBuilder builder(builder_capacity);
            Generic3AxisPedalOutputRecordBuilder record_builder(builder);
            record_builder.add_timestamp(&update_timestamp);
            builder.Finish(record_builder.Finish());
            callback(update_ns, builder.GetBufferPointer(), builder.GetSize());
        }
        return;
    }

    // MCAP logTime is update_ns for all records in one update() batch;
    // per-sample timing is in the embedded DeviceDataTimestamp.
    for (const auto& sample : m_pending_records)
    {
        auto fb = flatbuffers::GetRoot<Generic3AxisPedalOutput>(sample.buffer.data());
        if (!fb)
        {
            continue;
        }

        Generic3AxisPedalOutputT parsed;
        fb->UnPackTo(&parsed);

        flatbuffers::FlatBufferBuilder builder(builder_capacity);
        auto data_offset = Generic3AxisPedalOutput::Pack(builder, &parsed);
        Generic3AxisPedalOutputRecordBuilder record_builder(builder);
        record_builder.add_data(data_offset);
        record_builder.add_timestamp(&sample.timestamp);
        builder.Finish(record_builder.Finish());
        callback(update_ns, builder.GetBufferPointer(), builder.GetSize());
    }
}

const Generic3AxisPedalOutputTrackedT& LiveGeneric3AxisPedalTrackerImpl::get_data() const
{
    return m_tracked;
}

} // namespace core
