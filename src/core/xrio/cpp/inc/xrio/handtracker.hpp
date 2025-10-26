// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <array>
#include <memory>

namespace oxr
{

// Hand joint data structure
struct JointPose
{
    float position[3]; // x, y, z in meters
    float orientation[4]; // x, y, z, w (quaternion)
    float radius;
    bool is_valid;
};

// Hand tracking data for a single hand
struct HandData
{
    static constexpr size_t NUM_JOINTS = 26; // XR_HAND_JOINT_COUNT_EXT
    std::array<JointPose, NUM_JOINTS> joints;
    bool is_active;
    XrTime timestamp;
};

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
    const HandData& get_left_hand() const;
    const HandData& get_right_hand() const;

    // Get joint name for debugging
    static std::string get_joint_name(uint32_t joint_index);

protected:
    // Internal lifecycle methods - only accessible via friend classes
    friend class TeleopSession;

    std::shared_ptr<ITrackerImpl> initialize(const OpenXRSessionHandles& handles) override;

private:
    // Implementation class declaration (Pimpl idiom)
    class Impl : public ITrackerImpl
    {
    public:
        // Factory function for creating the Impl - returns nullptr on failure
        static std::unique_ptr<Impl> create(const OpenXRSessionHandles& handles);

        ~Impl();

        // Override from ITrackerImpl
        bool update(XrTime time) override;

        const HandData& get_left_hand() const;
        const HandData& get_right_hand() const;

    private:
        // Private constructor - only callable from factory function
        Impl(XrSpace base_space,
             XrHandTrackerEXT left_hand_tracker,
             XrHandTrackerEXT right_hand_tracker,
             PFN_xrCreateHandTrackerEXT pfn_create,
             PFN_xrDestroyHandTrackerEXT pfn_destroy,
             PFN_xrLocateHandJointsEXT pfn_locate);

        // Helper functions
        static bool create_hand_tracker(XrSession session,
                                        XrHandEXT hand_type,
                                        PFN_xrCreateHandTrackerEXT pfn_create,
                                        XrHandTrackerEXT& out_tracker);
        void cleanup();
        bool update_hand(XrHandTrackerEXT tracker, XrTime time, HandData& out_data);

        XrSpace base_space_;

        // Hand trackers
        XrHandTrackerEXT left_hand_tracker_;
        XrHandTrackerEXT right_hand_tracker_;

        // Hand data
        HandData left_hand_;
        HandData right_hand_;

        // Extension function pointers
        PFN_xrCreateHandTrackerEXT pfn_create_hand_tracker_;
        PFN_xrDestroyHandTrackerEXT pfn_destroy_hand_tracker_;
        PFN_xrLocateHandJointsEXT pfn_locate_hand_joints_;
    };

    // Weak pointer to impl (owned by session)
    std::weak_ptr<Impl> cached_impl_;
};

} // namespace oxr
