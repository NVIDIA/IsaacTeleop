// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/controller_tracker.hpp"

#include <deviceio_base/tracker_factory.hpp>
#include <schema/controller_bfbs_generated.h>

#include <XR_NVX1_action_context.h>

namespace core
{

// ============================================================================
// ControllerTracker Public Interface
// ============================================================================

std::vector<std::string> ControllerTracker::get_required_extensions() const
{
    return { XR_NVX1_ACTION_CONTEXT_EXTENSION_NAME };
}

std::string_view ControllerTracker::get_schema_text() const
{
    return std::string_view(reinterpret_cast<const char*>(ControllerSnapshotRecordBinarySchema::data()),
                            ControllerSnapshotRecordBinarySchema::size());
}

const ControllerSnapshotTrackedT& ControllerTracker::get_left_controller(const ITrackerSession& session) const
{
    return static_cast<const ControllerTrackerImpl&>(session.get_tracker_impl(*this)).get_left_controller();
}

const ControllerSnapshotTrackedT& ControllerTracker::get_right_controller(const ITrackerSession& session) const
{
    return static_cast<const ControllerTrackerImpl&>(session.get_tracker_impl(*this)).get_right_controller();
}

std::unique_ptr<ITrackerImpl> ControllerTracker::create_tracker_impl(ITrackerFactory& factory) const
{
    return factory.create_controller_tracker_impl(this);
}

} // namespace core
