// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/controller_tracker.hpp"

namespace core
{

// ============================================================================
// ControllerTracker Public Interface
// ============================================================================

const ControllerSnapshotTrackedT& ControllerTracker::get_left_controller(const ITrackerSession& session) const
{
    return static_cast<const ControllerTrackerImpl&>(session.get_tracker_impl(*this)).get_left_controller();
}

const ControllerSnapshotTrackedT& ControllerTracker::get_right_controller(const ITrackerSession& session) const
{
    return static_cast<const ControllerTrackerImpl&>(session.get_tracker_impl(*this)).get_right_controller();
}

} // namespace core
