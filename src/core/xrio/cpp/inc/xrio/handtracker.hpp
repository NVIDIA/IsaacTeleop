// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <schema/hand_generated.h>

#include <memory>

namespace core
{

// Hand tracker - tracks both left and right hands
// PUBLIC API: Only exposes query methods
class HandTracker : public ITracker
{
public:
    HandTracker();
    ~HandTracker() override;

    // Public API - what external users see
    std::vector<std::string> get_required_extensions() const override;
    std::string get_name() const override
    {
        return "HandTracker";
    }
    bool is_initialized() const override;

    // Query methods - public API for getting hand data
    const HandPoseT& get_left_hand() const;
    const HandPoseT& get_right_hand() const;

    // Get joint name for debugging
    static std::string get_joint_name(uint32_t joint_index);

protected:
    // Internal lifecycle methods - only accessible via friend classes
    friend class XrioSession;

    std::shared_ptr<ITrackerImpl> initialize(const OpenXRSessionHandles& handles) override;

private:
    // Implementation class declaration (Pimpl idiom)
    class Impl : public ITrackerImpl
    {
    public:
        // Constructor - throws std::runtime_error on failure
        explicit Impl(const OpenXRSessionHandles& handles);

        ~Impl();

        // Override from ITrackerImpl
        bool update(XrTime time) override;

        const HandPoseT& get_left_hand() const;
        const HandPoseT& get_right_hand() const;

    private:
        // Helper functions
        bool update_hand(XrHandTrackerEXT tracker, XrTime time, HandPoseT& out_data);

        XrSpace base_space_;

        // Hand trackers
        XrHandTrackerEXT left_hand_tracker_;
        XrHandTrackerEXT right_hand_tracker_;

        // Hand data
        HandPoseT left_hand_;
        HandPoseT right_hand_;

        // Extension function pointers
        PFN_xrCreateHandTrackerEXT pfn_create_hand_tracker_;
        PFN_xrDestroyHandTrackerEXT pfn_destroy_hand_tracker_;
        PFN_xrLocateHandJointsEXT pfn_locate_hand_joints_;
    };

    // Weak pointer to impl (owned by session)
    std::weak_ptr<Impl> cached_impl_;
};

} // namespace core
