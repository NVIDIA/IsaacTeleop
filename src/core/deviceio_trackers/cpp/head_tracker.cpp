// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/head_tracker.hpp"

#include <deviceio_base/tracker_factory.hpp>

namespace core
{

// ============================================================================
// HeadTracker
// ============================================================================

std::vector<std::string> HeadTracker::get_required_extensions() const
{
    return {};
}

std::unique_ptr<ITrackerImpl> HeadTracker::create_tracker_impl(ITrackerFactory& factory) const
{
    return factory.create_head_tracker_impl(this);
}

const HeadPoseTrackedT& HeadTracker::get_head(const ITrackerSession& session) const
{
    return static_cast<const HeadTrackerImpl&>(session.get_tracker_impl(*this)).get_head();
}

} // namespace core
