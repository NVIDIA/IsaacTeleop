// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/frame_metadata_tracker_orbbec.hpp"

#include <set>
#include <stdexcept>
#include <string>

namespace core
{

FrameMetadataTrackerOrbbec::FrameMetadataTrackerOrbbec(const std::string& collection_prefix,
                                                       const std::vector<OrbbecCameraStream>& streams,
                                                       size_t max_flatbuffer_size)
    : collection_prefix_(collection_prefix), streams_(streams), max_flatbuffer_size_(max_flatbuffer_size)
{
    if (collection_prefix_.empty())
        throw std::invalid_argument("FrameMetadataTrackerOrbbec: collection_prefix is required");
    if (streams_.empty())
        throw std::invalid_argument("FrameMetadataTrackerOrbbec: at least one stream is required");
    if (max_flatbuffer_size_ == 0)
        throw std::invalid_argument("FrameMetadataTrackerOrbbec: max_flatbuffer_size must be positive");

    std::set<OrbbecCameraStream> unique_streams;
    for (const auto stream : streams_)
    {
        const char* name = EnumNameOrbbecCameraStream(stream);
        if (name == nullptr)
        {
            throw std::invalid_argument("FrameMetadataTrackerOrbbec: invalid stream value " +
                                        std::to_string(static_cast<int>(stream)));
        }
        if (!unique_streams.insert(stream).second)
        {
            throw std::invalid_argument("FrameMetadataTrackerOrbbec: duplicate stream " + std::string(name));
        }
        stream_names_.emplace_back(name);
    }
}

const FrameMetadataOrbbecTrackedT& FrameMetadataTrackerOrbbec::get_stream_data(const ITrackerSession& session,
                                                                               size_t stream_index) const
{
    return static_cast<const IFrameMetadataTrackerOrbbecImpl&>(session.get_tracker_impl(*this)).get_stream_data(stream_index);
}

} // namespace core
