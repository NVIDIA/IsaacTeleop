// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/haply_device_tracker.hpp"

#include "inc/deviceio/deviceio_session.hpp"

#include <flatbuffers/flatbuffers.h>
#include <oxr_utils/oxr_time.hpp>
#include <schema/haply_device_bfbs_generated.h>

#include <vector>

namespace core
{

// ============================================================================
// HaplyDeviceTracker::Impl
// ============================================================================

class HaplyDeviceTracker::Impl : public ITrackerImpl
{
public:
    Impl(const OpenXRSessionHandles& handles, SchemaTrackerConfig config);

    bool update(XrTime time) override;
    void serialize_all(size_t channel_index, const RecordCallback& callback) const override;

    const HaplyDeviceOutputTrackedT& get_data() const;

private:
    SchemaTracker m_schema_reader;
    XrTimeConverter m_time_converter_;
    XrTime m_last_update_time_ = 0;
    bool m_collection_present = false;
    HaplyDeviceOutputTrackedT m_tracked;
    std::vector<SchemaTracker::SampleResult> m_pending_records;
};

HaplyDeviceTracker::Impl::Impl(const OpenXRSessionHandles& handles, SchemaTrackerConfig config)
    : m_schema_reader(handles, std::move(config)), m_time_converter_(handles)
{
}

bool HaplyDeviceTracker::Impl::update(XrTime time)
{
    m_last_update_time_ = time;
    m_pending_records.clear();
    m_collection_present = m_schema_reader.read_all_samples(m_pending_records);

    if (!m_collection_present)
    {
        // Device disappeared: clear tracked data so get_data() reflects absence.
        m_tracked.data.reset();
        return true;
    }

    // Deserialize only the last sample to keep m_tracked current for get_data().
    // Full per-sample deserialization is deferred to serialize_all().
    if (!m_pending_records.empty())
    {
        auto fb = flatbuffers::GetRoot<HaplyDeviceOutput>(m_pending_records.back().buffer.data());
        if (fb)
        {
            if (!m_tracked.data)
            {
                m_tracked.data = std::make_shared<HaplyDeviceOutputT>();
            }
            fb->UnPackTo(m_tracked.data.get());
        }
    }
    // When no samples arrive but the collection is present, m_tracked retains
    // the last seen value so get_data() reflects the most recently received state.

    return true;
}

void HaplyDeviceTracker::Impl::serialize_all(size_t channel_index, const RecordCallback& callback) const
{
    if (channel_index != 0)
    {
        return;
    }

    int64_t update_ns = m_time_converter_.convert_xrtime_to_monotonic_ns(m_last_update_time_);

    if (m_pending_records.empty())
    {
        if (!m_collection_present)
        {
            // Device disappeared: emit one empty record to mark the absence in the MCAP stream.
            DeviceDataTimestamp update_timestamp(update_ns, 0, 0);
            flatbuffers::FlatBufferBuilder builder(64);
            HaplyDeviceOutputRecordBuilder record_builder(builder);
            record_builder.add_timestamp(&update_timestamp);
            builder.Finish(record_builder.Finish());
            callback(update_ns, builder.GetBufferPointer(), builder.GetSize());
        }
        return;
    }

    for (const auto& sample : m_pending_records)
    {
        auto fb = flatbuffers::GetRoot<HaplyDeviceOutput>(sample.buffer.data());
        if (!fb)
        {
            continue;
        }

        HaplyDeviceOutputT parsed;
        fb->UnPackTo(&parsed);

        flatbuffers::FlatBufferBuilder builder(256);
        auto data_offset = HaplyDeviceOutput::Pack(builder, &parsed);
        HaplyDeviceOutputRecordBuilder record_builder(builder);
        record_builder.add_data(data_offset);
        record_builder.add_timestamp(&sample.timestamp);
        builder.Finish(record_builder.Finish());
        callback(update_ns, builder.GetBufferPointer(), builder.GetSize());
    }
}

const HaplyDeviceOutputTrackedT& HaplyDeviceTracker::Impl::get_data() const
{
    return m_tracked;
}

// ============================================================================
// HaplyDeviceTracker
// ============================================================================

HaplyDeviceTracker::HaplyDeviceTracker(const std::string& collection_id, size_t max_flatbuffer_size)
    : m_config{.collection_id = collection_id,
               .max_flatbuffer_size = max_flatbuffer_size,
               .tensor_identifier = "haply_device",
               .localized_name = "HaplyDeviceTracker"}
{
}

std::vector<std::string> HaplyDeviceTracker::get_required_extensions() const
{
    return SchemaTracker::get_required_extensions();
}

std::string_view HaplyDeviceTracker::get_name() const
{
    return "HaplyDeviceTracker";
}

std::string_view HaplyDeviceTracker::get_schema_name() const
{
    return "core.HaplyDeviceOutputRecord";
}

std::string_view HaplyDeviceTracker::get_schema_text() const
{
    return std::string_view(reinterpret_cast<const char*>(HaplyDeviceOutputRecordBinarySchema::data()),
                            HaplyDeviceOutputRecordBinarySchema::size());
}

const SchemaTrackerConfig& HaplyDeviceTracker::get_config() const
{
    return m_config;
}

const HaplyDeviceOutputTrackedT& HaplyDeviceTracker::get_data(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_data();
}

std::shared_ptr<ITrackerImpl> HaplyDeviceTracker::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<Impl>(handles, get_config());
}

} // namespace core
