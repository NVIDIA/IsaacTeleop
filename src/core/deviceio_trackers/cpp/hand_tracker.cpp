// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio_trackers/hand_tracker.hpp"

#include <deviceio_base/tracker_factory.hpp>

#include <array>

namespace core
{

namespace
{
constexpr uint32_t NUM_HAND_JOINTS = 26;
} // namespace

// ============================================================================
// HandTracker
// ============================================================================

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
    static constexpr std::array<const char*, NUM_HAND_JOINTS> joint_names = { { "Palm",
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
    static_assert(joint_names.size() == NUM_HAND_JOINTS,
                  "joint names count must match NUM_HAND_JOINTS (XR_HAND_JOINT_COUNT_EXT)");

    if (joint_index < joint_names.size())
    {
        return joint_names[joint_index];
    }
    return "Unknown";
}

} // namespace core
