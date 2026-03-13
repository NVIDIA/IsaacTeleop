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
        return TRACKER_NAME;
    }
    std::string_view get_schema_name() const override
    {
        return SCHEMA_NAME;
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

    // Query method - public API for getting body pose data (tracked.data is null when inactive)
    const FullBodyPosePicoTrackedT& get_body_pose(const DeviceIOSession& session) const;

    // Tracker-specific impl interface (public so out-of-class live impl in .cpp can inherit)
    struct IImpl
    {
        virtual ~IImpl() = default;
        virtual const FullBodyPosePicoTrackedT& get_body_pose() const = 0;
    };

private:
    static constexpr const char* TRACKER_NAME = "FullBodyTrackerPico";
    static constexpr const char* SCHEMA_NAME = "core.FullBodyPosePicoRecord";

    std::shared_ptr<ILiveTrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;
    std::shared_ptr<IReplayTrackerImpl> create_replay_tracker(const ITrackerSession& session) const override;

    class ReplayImpl : public IReplayTrackerImpl, public IImpl
    {
    public:
        explicit ReplayImpl(const ITrackerSession& session);

        bool update_replay(int64_t replay_time_ns) override;

        const FullBodyPosePicoTrackedT& get_body_pose() const override;

    private:
        const ITrackerSession* session_;
        FullBodyPosePicoTrackedT tracked_;
    };
};

} // namespace core
