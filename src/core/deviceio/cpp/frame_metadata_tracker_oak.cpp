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
        // Try to read new data from tensor stream
        if (m_schema_reader.read_buffer(m_buffer))
        {
            auto fb = GetFrameMetadata(m_buffer.data());
            if (fb)
            {
                fb->UnPackTo(&m_data);
                return true;
            }
        }
        // Return true even if no new data - we're still running
        return true;
    }

    Timestamp serialize(flatbuffers::FlatBufferBuilder& builder) const override
    {
        auto offset = FrameMetadata::Pack(builder, &m_data);
        builder.Finish(offset);
        return m_data.timestamp ? *m_data.timestamp : Timestamp{};
    }

    const FrameMetadataT& get_data() const
    {
        return m_data;
    }

private:
    SchemaTracker m_schema_reader;
    std::vector<uint8_t> m_buffer;
    FrameMetadataT m_data;
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
    return "core.FrameMetadata";
}

std::string_view FrameMetadataTrackerOak::get_schema_text() const
{
    return std::string_view(
        reinterpret_cast<const char*>(FrameMetadataBinarySchema::data()), FrameMetadataBinarySchema::size());
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
