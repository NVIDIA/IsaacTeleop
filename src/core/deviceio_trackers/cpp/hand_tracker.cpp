// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/hand_tracker.hpp"

namespace core
{

// ============================================================================
// HandTracker
// ============================================================================

const HandPoseTrackedT& HandTracker::get_left_hand(const ITrackerSession& session) const
{
    return static_cast<const IHandTrackerImpl&>(session.get_tracker_impl(*this)).get_left_hand();
}

const HandPoseTrackedT& HandTracker::get_right_hand(const ITrackerSession& session) const
{
    return static_cast<const IHandTrackerImpl&>(session.get_tracker_impl(*this)).get_right_hand();
}

} // namespace core
