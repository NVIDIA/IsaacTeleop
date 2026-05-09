// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/external_skeleton_tracker.hpp"

namespace core
{

ExternalSkeletonTracker::ExternalSkeletonTracker(const std::string& collection_id, size_t max_flatbuffer_size)
    : collection_id_(collection_id), max_flatbuffer_size_(max_flatbuffer_size)
{
}

const ExternalSkeletonPoseTrackedT& ExternalSkeletonTracker::get_skeleton_pose(const ITrackerSession& session) const
{
    return static_cast<const IExternalSkeletonTrackerImpl&>(session.get_tracker_impl(*this)).get_skeleton_pose();
}

} // namespace core
