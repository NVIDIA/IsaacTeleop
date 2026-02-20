// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/full_body_bfbs_generated.h>
#include <schema/full_body_generated.h>

#include <memory>

namespace core
{

// Full body tracker for PICO devices using XR_BD_body_tracking extension
// Tracks 24 body joints from pelvis to hands
// PUBLIC API: Only exposes query methods
class FullBodyTrackerPico : public ITracker
{
public:
    // Number of joints in XR_BD_body_tracking (0-23)
    static constexpr uint32_t JOINT_COUNT = 24;

    // Public API - what external users see
    std::vector<std::string> get_required_extensions() const override;

    std::string_view get_name() const override
    {
        return "FullBodyTrackerPico";
    }

    std::string_view get_schema_name() const override
    {
        return "core.FullBodyPosePicoRecord";
    }

    std::string_view get_schema_text() const override
    {
        return std::string_view(reinterpret_cast<const char*>(FullBodyPosePicoRecordBinarySchema::data()),
                                FullBodyPosePicoRecordBinarySchema::size());
    }

    std::vector<std::string> get_record_channels() const override
    {
        return { "full_body" };
    }

    // Query method - public API for getting body pose data (returns tracked output with timestamp)
    const FullBodyPosePicoTrackedT& get_body_pose(const DeviceIOSession& session) const;

private:
    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;
};

} // namespace core
