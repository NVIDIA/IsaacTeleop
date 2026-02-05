// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/frame_metadata_tracker.hpp"

#include "inc/deviceio/deviceio_session.hpp"

#include <flatbuffers/flatbuffers.h>
#include <schema/camera_bfbs_generated.h>

#include <vector>

namespace core
{

// ============================================================================
// FrameMetadataTracker::Impl
// ============================================================================

class FrameMetadataTracker::Impl : public SchemaTracker::Impl
{
public:
    Impl(const OpenXRSessionHandles& handles, SchemaConfig config) : SchemaTracker::Impl(handles, std::move(config))
    {
    }

    bool update(XrTime /* time */) override
    {
        // Try to read new data from tensor stream
        if (read_buffer(buffer_))
        {
            auto fb = GetFrameMetadata(buffer_.data());
            if (fb)
            {
                fb->UnPackTo(&data_);
                ++read_count_;
                return true;
            }
        }
        // Return true even if no new data - we're still running
        return true;
    }

    Timestamp serialize(flatbuffers::FlatBufferBuilder& builder) const override
    {
        auto offset = FrameMetadata::Pack(builder, &data_);
        builder.Finish(offset);
        // Extract timestamp from FrameMetadata
        if (data_.timestamp)
        {
            return *data_.timestamp;
        }
        return Timestamp{};
    }

    const FrameMetadataT& get_data() const
    {
        return data_;
    }

    size_t get_read_count() const
    {
        return read_count_;
    }

private:
    std::vector<uint8_t> buffer_;
    FrameMetadataT data_;
    size_t read_count_ = 0;
};

// ============================================================================
// FrameMetadataTracker
// ============================================================================

FrameMetadataTracker::FrameMetadataTracker(const std::string& collection_id, size_t max_flatbuffer_size)
    : SchemaTracker(SchemaConfig{ .schema_identifier = collection_id,
                                  .max_flatbuffer_size = max_flatbuffer_size,
                                  .localized_name = "FrameMetadataTracker" })
{
}

std::string_view FrameMetadataTracker::get_name() const
{
    return "FrameMetadataTracker";
}

std::string_view FrameMetadataTracker::get_schema_name() const
{
    return "core.FrameMetadata";
}

std::string_view FrameMetadataTracker::get_schema_text() const
{
    return std::string_view(
        reinterpret_cast<const char*>(FrameMetadataBinarySchema::data()), FrameMetadataBinarySchema::size());
}

const FrameMetadataT& FrameMetadataTracker::get_data(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_data();
}

size_t FrameMetadataTracker::get_read_count(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_read_count();
}

std::shared_ptr<ITrackerImpl> FrameMetadataTracker::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<Impl>(handles, get_config());
}

} // namespace core
