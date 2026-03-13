// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <oxr_utils/oxr_time.hpp>
#include <schema/hand_bfbs_generated.h>
#include <schema/hand_generated.h>

#include <memory>

namespace core
{

// Hand tracker - tracks both left and right hands
// PUBLIC API: Only exposes query methods
class HandTracker : public ITracker
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
            reinterpret_cast<const char*>(HandPoseRecordBinarySchema::data()), HandPoseRecordBinarySchema::size());
    }
    std::vector<std::string> get_record_channels() const override
    {
        return { "left_hand", "right_hand" };
    }

    // Query methods - public API for getting hand data (tracked.data is null when inactive)
    const HandPoseTrackedT& get_left_hand(const DeviceIOSession& session) const;
    const HandPoseTrackedT& get_right_hand(const DeviceIOSession& session) const;

    // Get joint name for debugging
    static std::string get_joint_name(uint32_t joint_index);

private:
    static constexpr const char* TRACKER_NAME = "HandTracker";
    static constexpr const char* SCHEMA_NAME = "core.HandPoseRecord";

    std::shared_ptr<ILiveTrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;
    std::shared_ptr<IReplayTrackerImpl> create_replay_tracker(const ITrackerSession& session) const override;

    struct IImpl
    {
        virtual ~IImpl() = default;
        virtual const HandPoseTrackedT& get_left_hand() const = 0;
        virtual const HandPoseTrackedT& get_right_hand() const = 0;
    };

    class Impl : public ILiveTrackerImpl, public IImpl
    {
    public:
        // Constructor - throws std::runtime_error on failure
        explicit Impl(const OpenXRSessionHandles& handles);
        ~Impl();

        bool update_live(int64_t system_monotonic_time_ns) override;

        void serialize_all(size_t channel_index, const RecordCallback& callback) const override;

        const HandPoseTrackedT& get_left_hand() const override;
        const HandPoseTrackedT& get_right_hand() const override;

    private:
        // Helper functions
        bool update_hand(XrHandTrackerEXT tracker, XrTime time, HandPoseTrackedT& tracked);

        XrTimeConverter time_converter_;
        XrSpace base_space_;

        // Hand trackers
        XrHandTrackerEXT left_hand_tracker_;
        XrHandTrackerEXT right_hand_tracker_;

        // Hand data (tracked.data is null when inactive)
        HandPoseTrackedT left_tracked_;
        HandPoseTrackedT right_tracked_;
        int64_t last_update_time_ns_ = 0; // monotonic ns; XrTime only for OpenXR calls

        // Extension function pointers
        PFN_xrCreateHandTrackerEXT pfn_create_hand_tracker_;
        PFN_xrDestroyHandTrackerEXT pfn_destroy_hand_tracker_;
        PFN_xrLocateHandJointsEXT pfn_locate_hand_joints_;
    };

    class ReplayImpl : public IReplayTrackerImpl, public IImpl
    {
    public:
        explicit ReplayImpl(const ITrackerSession& session);

        bool update_replay(int64_t replay_time_ns) override;

        const HandPoseTrackedT& get_left_hand() const override;
        const HandPoseTrackedT& get_right_hand() const override;

    private:
        const ITrackerSession* session_;
        HandPoseTrackedT left_tracked_;
        HandPoseTrackedT right_tracked_;
    };
};

} // namespace core
