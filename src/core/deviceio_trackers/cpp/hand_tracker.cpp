// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/hand_tracker.hpp"

#include <deviceio_base/tracker_factory.hpp>

#include <array>

namespace core
{

// ============================================================================
// HandTracker
// ============================================================================

std::vector<std::string> HandTracker::get_required_extensions() const
{
    return { XR_EXT_HAND_TRACKING_EXTENSION_NAME };
}

std::unique_ptr<ITrackerImpl> HandTracker::create_tracker_impl(ITrackerFactory& factory) const
{
    return factory.create_hand_tracker_impl(this);
}

const HandPoseTrackedT& HandTracker::get_left_hand(const ITrackerSession& session) const
{
    return static_cast<const HandTrackerImpl&>(session.get_tracker_impl(*this)).get_left_hand();
}

const HandPoseTrackedT& HandTracker::get_right_hand(const ITrackerSession& session) const
{
    return static_cast<const HandTrackerImpl&>(session.get_tracker_impl(*this)).get_right_hand();
}

std::string HandTracker::get_joint_name(uint32_t joint_index)
{
    static constexpr std::array<const char*, XR_HAND_JOINT_COUNT_EXT> joint_names = { { "Palm",
                                                                                        "Wrist",
                                                                                        "Thumb_Metacarpal",
                                                                                        "Thumb_Proximal",
                                                                                        "Thumb_Distal",
                                                                                        "Thumb_Tip",
                                                                                        "Index_Metacarpal",
                                                                                        "Index_Proximal",
                                                                                        "Index_Intermediate",
                                                                                        "Index_Distal",
                                                                                        "Index_Tip",
                                                                                        "Middle_Metacarpal",
                                                                                        "Middle_Proximal",
                                                                                        "Middle_Intermediate",
                                                                                        "Middle_Distal",
                                                                                        "Middle_Tip",
                                                                                        "Ring_Metacarpal",
                                                                                        "Ring_Proximal",
                                                                                        "Ring_Intermediate",
                                                                                        "Ring_Distal",
                                                                                        "Ring_Tip",
                                                                                        "Little_Metacarpal",
                                                                                        "Little_Proximal",
                                                                                        "Little_Intermediate",
                                                                                        "Little_Distal",
                                                                                        "Little_Tip" } };
    static_assert(joint_names.size() == XR_HAND_JOINT_COUNT_EXT, "joint names count must match XR_HAND_JOINT_COUNT_EXT");

    if (joint_index < joint_names.size())
    {
        return joint_names[joint_index];
    }
    return "Unknown";
}

} // namespace core
