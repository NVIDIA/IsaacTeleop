// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/full_body_generated.h>

#include <cstdint>
#include <memory>

namespace core
{

// Full body tracker for PICO devices using XR_BD_body_tracking extension.
// Tracks 24 body joints from pelvis to hands.
class FullBodyTrackerPico : public ITracker
{
public:
    //! Number of joints in XR_BD_body_tracking (0-23)
    static constexpr uint32_t JOINT_COUNT = 24;

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
        return { "full_body" };
    }

    // Query method - tracked.data is null when the body tracker is inactive
    const FullBodyPosePicoTrackedT& get_body_pose(const DeviceIOSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "FullBodyTrackerPico";
    static constexpr const char* SCHEMA_NAME = "core.FullBodyPosePicoRecord";

    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    class Impl;
};

} // namespace core
