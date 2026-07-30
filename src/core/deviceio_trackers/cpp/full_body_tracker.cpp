// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/full_body_tracker.hpp"

namespace core
{

const FullBodyPoseTrackedT& FullBodyTracker::get_body_pose(const ITrackerSession& session) const
{
    return static_cast<const IFullBodyTrackerImpl&>(session.get_tracker_impl(*this)).get_body_pose();
}

} // namespace core
