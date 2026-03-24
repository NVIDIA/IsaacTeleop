// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/generic_3axis_pedal_tracker.hpp"

namespace core
{

// ============================================================================
// Generic3AxisPedalTracker
// ============================================================================

Generic3AxisPedalTracker::Generic3AxisPedalTracker(const std::string& collection_id, size_t max_flatbuffer_size)
    : collection_id_(collection_id), max_flatbuffer_size_(max_flatbuffer_size)
{
}

const Generic3AxisPedalOutputTrackedT& Generic3AxisPedalTracker::get_data(const ITrackerSession& session) const
{
    return static_cast<const Generic3AxisPedalTrackerImpl&>(session.get_tracker_impl(*this)).get_data();
}

} // namespace core
