// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

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

    // Query methods - public API for getting hand data
    const HandPoseT& get_left_hand(const DeviceIOSession& session) const;
    const HandPoseT& get_right_hand(const DeviceIOSession& session) const;

    // Get joint name for debugging
    static std::string get_joint_name(uint32_t joint_index);

private:
    static constexpr const char* TRACKER_NAME = "HandTracker";
    static constexpr const char* SCHEMA_NAME = "core.HandPoseRecord";

    std::shared_ptr<ITrackerImpl> create_tracker(const OpenXRSessionHandles& handles) const override;

    class Impl : public ITrackerImpl
    {
    public:
        // Constructor - throws std::runtime_error on failure
        explicit Impl(const OpenXRSessionHandles& handles);

        ~Impl();

        // Override from ITrackerImpl
        bool update(XrTime time) override;

        DeviceDataTimestamp serialize(flatbuffers::FlatBufferBuilder& builder, size_t channel_index) const override;

        const HandPoseT& get_left_hand() const;
        const HandPoseT& get_right_hand() const;

    private:
        bool update_hand(XrHandTrackerEXT tracker, XrTime time, HandPoseT& out_data);

        XrSpace base_space_;

        // Hand trackers
        XrHandTrackerEXT left_hand_tracker_;
        XrHandTrackerEXT right_hand_tracker_;

        // Hand data
        HandPoseT left_hand_;
        HandPoseT right_hand_;

        // Timestamp from last update
        DeviceDataTimestamp last_timestamp_{};

        // Extension function pointers
        PFN_xrCreateHandTrackerEXT pfn_create_hand_tracker_;
        PFN_xrDestroyHandTrackerEXT pfn_destroy_hand_tracker_;
        PFN_xrLocateHandJointsEXT pfn_locate_hand_joints_;
    };
};

} // namespace core
