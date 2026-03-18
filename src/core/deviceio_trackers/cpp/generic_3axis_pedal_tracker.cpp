// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/generic_3axis_pedal_tracker.hpp"

#include <deviceio_base/tracker_factory.hpp>

namespace core
{

// ============================================================================
// Generic3AxisPedalTracker
// ============================================================================

Generic3AxisPedalTracker::Generic3AxisPedalTracker(const std::string& collection_id, size_t max_flatbuffer_size)
    : collection_id_(collection_id), max_flatbuffer_size_(max_flatbuffer_size)
{
}

std::vector<std::string> Generic3AxisPedalTracker::get_required_extensions() const
{
    // Tensor-data extension required by SchemaTracker-based trackers.
    // XrTimeConverter extensions are added separately by DeviceIOSession::get_required_extensions().
    return { "XR_NVX1_tensor_data" };
}

const Generic3AxisPedalOutputTrackedT& Generic3AxisPedalTracker::get_data(const ITrackerSession& session) const
{
    return static_cast<const Generic3AxisPedalTrackerImpl&>(session.get_tracker_impl(*this)).get_data();
}

std::unique_ptr<ITrackerImpl> Generic3AxisPedalTracker::create_tracker_impl(ITrackerFactory& factory) const
{
    return factory.create_generic_3axis_pedal_tracker_impl(this);
}

} // namespace core
