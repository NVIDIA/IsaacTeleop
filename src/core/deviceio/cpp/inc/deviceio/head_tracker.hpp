// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <oxr_utils/oxr_funcs.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <schema/head_bfbs_generated.h>
#include <schema/head_generated.h>

#include <memory>

namespace core
{

// Head tracker - tracks HMD pose (returns HeadPoseTrackedT from FlatBuffer schema)
// PUBLIC API: Only exposes query methods
class HeadTracker : public ITracker
{
public:
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
        return std::string_view(
            reinterpret_cast<const char*>(HeadPoseRecordBinarySchema::data()), HeadPoseRecordBinarySchema::size());
    }
    std::vector<std::string> get_record_channels() const override
    {
        return { "head" };
    }

    // Query methods - public API for getting head data (tracked.data is always set)
    const HeadPoseTrackedT& get_head(const DeviceIOSession& session) const;

private:
    static constexpr const char* TRACKER_NAME = "HeadTracker";
    static constexpr const char* SCHEMA_NAME = "core.HeadPoseRecord";

    std::shared_ptr<ILiveTrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;
    std::shared_ptr<IReplayTrackerImpl> create_replay_tracker(const ITrackerSession& session) const override;

    struct IImpl
    {
        virtual ~IImpl() = default;
        virtual const HeadPoseTrackedT& get_head() const = 0;
    };

    class Impl : public ILiveTrackerImpl, public IImpl
    {
    public:
        explicit Impl(const OpenXRSessionHandles& handles);

        // Override from ILiveTrackerImpl
        bool update_live(int64_t system_monotonic_time_ns) override;

        void serialize_all(size_t channel_index, const RecordCallback& callback) const override;

        const HeadPoseTrackedT& get_head() const override;

    private:
        const OpenXRCoreFunctions core_funcs_;
        XrTimeConverter time_converter_;
        XrSpace base_space_;
        XrSpacePtr view_space_;
        HeadPoseTrackedT tracked_;
        int64_t last_update_time_ns_ = 0; // monotonic ns; XrTime only for OpenXR calls
    };

    class ReplayImpl : public IReplayTrackerImpl, public IImpl
    {
    public:
        explicit ReplayImpl(const ITrackerSession& session);

        bool update_replay(int64_t replay_time_ns) override;

        const HeadPoseTrackedT& get_head() const override;

    private:
        const ITrackerSession* session_;
        HeadPoseTrackedT tracked_;
    };
};

} // namespace core
