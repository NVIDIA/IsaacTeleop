// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/hand_tracker_base.hpp>
#include <schema/hand_generated.h>

#include <string>

namespace core
{

// Tracks both left and right hands via XR_EXT_hand_tracking.
class HandTracker : public ITracker
{
public:
    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    // Query methods - tracked.data is null when the hand is inactive
    const HandPoseTrackedT& get_left_hand(const ITrackerSession& session) const;
    const HandPoseTrackedT& get_right_hand(const ITrackerSession& session) const;

    /** @brief Get joint name for debugging. */
    static std::string get_joint_name(uint32_t joint_index);

private:
    static constexpr const char* TRACKER_NAME = "HandTracker";
};

} // namespace core
