// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/hand_tracker_base.hpp>
#include <schema/hand_generated.h>

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

    // Query methods:
    // - tracked.data is null when the hand is inactive.
    // - when tracked.data is non-null, nested fields in HandPoseT are safe to read.
    const HandPoseTrackedT& get_left_hand(const ITrackerSession& session) const;
    const HandPoseTrackedT& get_right_hand(const ITrackerSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "HandTracker";
};

} // namespace core
