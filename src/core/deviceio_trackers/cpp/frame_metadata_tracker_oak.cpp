// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/frame_metadata_tracker_oak.hpp"

namespace core
{

// ============================================================================
// FrameMetadataTrackerOak
// ============================================================================

FrameMetadataTrackerOak::FrameMetadataTrackerOak(const std::string& collection_id, size_t max_flatbuffer_size)
    : collection_id_(collection_id), max_flatbuffer_size_(max_flatbuffer_size)
{
    // No-op: members set in the initializer list.
}

const FrameMetadataOakTrackedT& FrameMetadataTrackerOak::get_data(const ITrackerSession& session) const
{
    return static_cast<const IFrameMetadataTrackerOakImpl&>(session.get_tracker_impl(*this)).get_data();
}

} // namespace core
