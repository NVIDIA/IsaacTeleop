// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
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
    struct StreamState
    {
        std::unique_ptr<SchemaTracker> reader;
        FrameMetadataOakT data;
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
            if (stream.reader->read_buffer(m_buffer))
            {
                auto fb = flatbuffers::GetRoot<FrameMetadataOak>(m_buffer.data());
                if (fb)
                    fb->UnPackTo(&stream.data);
            }
        }

        m_data.streams.clear();
        for (const auto& s : m_streams)
            m_data.streams.push_back(std::make_unique<FrameMetadataOakT>(s.data));

        return true;
    }

    Timestamp serialize(flatbuffers::FlatBufferBuilder& builder) const override
    {
        auto offset = CameraMetadataOak::Pack(builder, &m_data);
        builder.Finish(offset);

        Timestamp latest{};
        for (const auto& entry : m_data.streams)
        {
            if (entry->timestamp && entry->timestamp->device_time() > latest.device_time())
                latest = *entry->timestamp;
        }
        return latest;
    }

    const CameraMetadataOakT& get_data() const
    {
        return m_data;
    }

private:
    std::vector<StreamState> m_streams;
    std::vector<uint8_t> m_buffer;
    CameraMetadataOakT m_data;
};

// ============================================================================
// FrameMetadataTrackerOak
// ============================================================================

FrameMetadataTrackerOak::FrameMetadataTrackerOak(const std::string& collection_prefix,
                                                 const std::vector<StreamType>& streams,
                                                 size_t max_flatbuffer_size)
{
    for (auto type : streams)
    {
        m_configs.push_back({ .collection_id = collection_prefix + "/" + EnumNameStreamType(type),
                              .max_flatbuffer_size = max_flatbuffer_size,
                              .tensor_identifier = "frame_metadata",
                              .localized_name = std::string("FrameMetadataTracker_") + EnumNameStreamType(type) });
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
    return "core.CameraMetadataOak";
}

std::string_view FrameMetadataTrackerOak::get_schema_text() const
{
    return std::string_view(
        reinterpret_cast<const char*>(CameraMetadataOakBinarySchema::data()), CameraMetadataOakBinarySchema::size());
}

const CameraMetadataOakT& FrameMetadataTrackerOak::get_data(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_data();
}

std::shared_ptr<ITrackerImpl> FrameMetadataTrackerOak::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<Impl>(handles, m_configs);
}

} // namespace core
