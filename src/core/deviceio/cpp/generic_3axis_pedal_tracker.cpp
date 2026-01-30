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

class Generic3AxisPedalTracker::Impl : public SchemaTracker::Impl
{
public:
    Impl(const OpenXRSessionHandles& handles, SchemaTrackerConfig config)
        : SchemaTracker::Impl(handles, std::move(config))
    {
    }

    bool update(XrTime /* time */) override
    {
        // Try to read new data from tensor stream
        if (read_buffer(buffer_))
        {
            auto fb = GetGeneric3AxisPedalOutput(buffer_.data());
            if (fb)
            {
                fb->UnPackTo(&data_);
                return true;
            }
        }
        // Return true even if no new data - we're still running
        return true;
    }

    Timestamp serialize(flatbuffers::FlatBufferBuilder& builder) const override
    {
        auto offset = Generic3AxisPedalOutput::Pack(builder, &data_);
        builder.Finish(offset);
        return data_.timestamp ? *data_.timestamp : Timestamp{};
    }

    const Generic3AxisPedalOutputT& get_data() const
    {
        return data_;
    }

private:
    std::vector<uint8_t> buffer_;
    Generic3AxisPedalOutputT data_;
};

// ============================================================================
// Generic3AxisPedalTracker
// ============================================================================

Generic3AxisPedalTracker::Generic3AxisPedalTracker(const std::string& collection_id, size_t max_flatbuffer_size)
    : SchemaTracker(SchemaTrackerConfig{ .collection_id = collection_id,
                                         .max_flatbuffer_size = max_flatbuffer_size,
                                         .tensor_identifier = "generic_3axis_pedal",
                                         .localized_name = "Generic3AxisPedalTracker" })
{
}

std::string_view Generic3AxisPedalTracker::get_name() const
{
    return "Generic3AxisPedalTracker";
}

std::string_view Generic3AxisPedalTracker::get_schema_name() const
{
    return "core.Generic3AxisPedalOutput";
}

std::string_view Generic3AxisPedalTracker::get_schema_text() const
{
    // TODO: Return binary schema from pedals_bfbs_generated.h when available
    return {};
}

const Generic3AxisPedalOutputT& Generic3AxisPedalTracker::get_data(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_data();
}

size_t Generic3AxisPedalTracker::get_read_count(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_read_count();
}

std::shared_ptr<ITrackerImpl> Generic3AxisPedalTracker::create_tracker(const OpenXRSessionHandles& handles) const
{
    return std::make_shared<Impl>(handles, get_config());
}

} // namespace core
