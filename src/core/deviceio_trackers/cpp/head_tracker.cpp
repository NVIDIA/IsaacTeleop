// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/head_tracker.hpp"

namespace core
{

// ============================================================================
// HeadTracker
// ============================================================================

const HeadPoseTrackedT& HeadTracker::get_head(const ITrackerSession& session) const
{
    return static_cast<const IHeadTrackerImpl&>(session.get_tracker_impl(*this)).get_head();
}

} // namespace core
