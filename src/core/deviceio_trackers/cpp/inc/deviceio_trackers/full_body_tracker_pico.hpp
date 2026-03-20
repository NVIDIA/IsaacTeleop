// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_base/full_body_tracker_pico_base.hpp>
#include <schema/full_body_generated.h>

#include <cstdint>
#include <memory>

namespace core
{

// Full body tracker for PICO devices using XR_BD_body_tracking.
// Tracks 24 body joints (indices 0-23) from pelvis to hands.
class FullBodyTrackerPico : public ITracker
{
public:
    //! Number of joints in XR_BD_body_tracking (0-23).
    static constexpr uint32_t JOINT_COUNT = 24;

    std::string_view get_name() const override
    {
        return TRACKER_NAME;
    }

    // Double-dispatch: calls factory.create_full_body_tracker_pico_impl()
    std::unique_ptr<ITrackerImpl> create_tracker_impl(ITrackerFactory& factory) const override;

    // Query method - tracked.data is null when the body tracker is inactive
    const FullBodyPosePicoTrackedT& get_body_pose(const ITrackerSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "FullBodyTrackerPico";
};

} // namespace core
