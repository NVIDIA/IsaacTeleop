// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/spacemouse_tracker.hpp"

namespace core
{

// ============================================================================
// SpaceMouseTracker
// ============================================================================

SpaceMouseTracker::SpaceMouseTracker(const std::string& collection_id, size_t max_flatbuffer_size)
    : collection_id_(collection_id), max_flatbuffer_size_(max_flatbuffer_size)
{
}

const SpaceMouseOutputTrackedT& SpaceMouseTracker::get_data(const ITrackerSession& session) const
{
    return static_cast<const ISpaceMouseTrackerImpl&>(session.get_tracker_impl(*this)).get_data();
}

} // namespace core
