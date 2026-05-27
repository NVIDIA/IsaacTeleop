// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/controller_tracker.hpp"

namespace core
{

// ============================================================================
// ControllerTracker Public Interface
// ============================================================================

const ControllerSnapshotTrackedT& ControllerTracker::get_left_controller(const ITrackerSession& session) const
{
    return static_cast<const IControllerTrackerImpl&>(session.get_tracker_impl(*this)).get_left_controller();
}

const ControllerSnapshotTrackedT& ControllerTracker::get_right_controller(const ITrackerSession& session) const
{
    return static_cast<const IControllerTrackerImpl&>(session.get_tracker_impl(*this)).get_right_controller();
}

void ControllerTracker::apply_haptic_feedback(
    const ITrackerSession& session, bool is_left, float amplitude, float frequency_hz, float duration_s) const
{
    static_cast<const IControllerTrackerImpl&>(session.get_tracker_impl(*this))
        .apply_haptic_feedback(is_left, amplitude, frequency_hz, duration_s);
}

} // namespace core
