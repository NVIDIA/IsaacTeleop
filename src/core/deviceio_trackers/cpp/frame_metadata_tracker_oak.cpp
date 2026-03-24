// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/frame_metadata_tracker_oak.hpp"

#include <stdexcept>
#include <string>

namespace core
{

// ============================================================================
// FrameMetadataTrackerOak
// ============================================================================

FrameMetadataTrackerOak::FrameMetadataTrackerOak(const std::string& collection_prefix,
                                                 const std::vector<StreamType>& streams,
                                                 size_t max_flatbuffer_size)
    : collection_prefix_(collection_prefix), streams_(streams), max_flatbuffer_size_(max_flatbuffer_size)
{
    if (streams.empty())
    {
        throw std::runtime_error("FrameMetadataTrackerOak: at least one stream is required");
    }

    for (auto type : streams)
    {
        const char* name = EnumNameStreamType(type);
        if (name == nullptr)
        {
            throw std::invalid_argument("FrameMetadataTrackerOak: invalid StreamType value " +
                                        std::to_string(static_cast<int>(type)));
        }
        m_stream_names.emplace_back(name);
    }
}

const FrameMetadataOakTrackedT& FrameMetadataTrackerOak::get_stream_data(const ITrackerSession& session,
                                                                         size_t stream_index) const
{
    return static_cast<const IFrameMetadataTrackerOakImpl&>(session.get_tracker_impl(*this)).get_stream_data(stream_index);
}

} // namespace core
