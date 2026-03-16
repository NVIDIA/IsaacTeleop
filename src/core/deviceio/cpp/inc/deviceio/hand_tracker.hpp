// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/hand_generated.h>

#include <memory>
#include <string>

namespace core
{

// Hand tracker - tracks both left and right hands via XR_EXT_hand_tracking
class HandTracker : public ITracker
{
public:
    std::vector<std::string> get_required_extensions() const override;
    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }
    std::string_view get_schema_name() const override
    {
        return SCHEMA_NAME;
    }
    std::string_view get_schema_text() const override;
    std::vector<std::string> get_record_channels() const override
    {
        return { "left_hand", "right_hand" };
    }

    // Query methods - tracked.data is null when the hand is inactive
    const HandPoseTrackedT& get_left_hand(const DeviceIOSession& session) const;
    const HandPoseTrackedT& get_right_hand(const DeviceIOSession& session) const;

    /** @brief Get joint name for debugging. */
    static std::string get_joint_name(uint32_t joint_index);

private:
    static constexpr const char* TRACKER_NAME = "HandTracker";
    static constexpr const char* SCHEMA_NAME = "core.HandPoseRecord";

    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    class Impl;
};

} // namespace core
