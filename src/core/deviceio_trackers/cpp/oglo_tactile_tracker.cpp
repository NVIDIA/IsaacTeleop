// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/oglo_tactile_tracker.hpp"

namespace core
{

// ============================================================================
// OgloTactileTracker
// ============================================================================

OgloTactileTracker::OgloTactileTracker(const std::string& collection_id, size_t max_flatbuffer_size)
    : collection_id_(collection_id), max_flatbuffer_size_(max_flatbuffer_size)
{
}

const OgloGloveSampleTrackedT& OgloTactileTracker::get_data(const ITrackerSession& session) const
{
    return static_cast<const IOgloTactileTrackerImpl&>(session.get_tracker_impl(*this)).get_data();
}

} // namespace core
