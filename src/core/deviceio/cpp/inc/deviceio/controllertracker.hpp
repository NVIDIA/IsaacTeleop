// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <array>
#include <memory>

namespace core
{

// Which hand/controller
enum class Hand
{
    Left,
    Right
};

// Convert hand enum to string
inline const char* to_string(Hand hand)
{
    return hand == Hand::Left ? "Left" : "Right";
}

// Controller input state with proper types
struct ControllerInputState
{
    // Buttons (bool)
    bool primary_click = false;
    bool secondary_click = false;
    bool thumbstick_click = false;

    // Axes (float)
    float thumbstick_x = 0.0f;
    float thumbstick_y = 0.0f;
    float squeeze_value = 0.0f;
    float trigger_value = 0.0f;
};

// Controller pose data
struct ControllerPose
{
    float position[3] = { 0.0f, 0.0f, 0.0f }; // x, y, z in meters
    float orientation[4] = { 0.0f, 0.0f, 0.0f, 1.0f }; // x, y, z, w (quaternion)
    bool is_valid = false;
};

// Snapshot data for a single controller
struct ControllerSnapshot
{
    ControllerPose grip_pose;
    ControllerPose aim_pose;
    ControllerInputState inputs;
    bool is_active = false;
    XrTime timestamp = 0;
};

// Controller tracker - tracks both left and right controllers
// Updates all controller state (poses + inputs) each frame
class ControllerTracker : public ITracker
{
public:
    ControllerTracker();
    ~ControllerTracker() override;

    // Public API - what external users see
    std::vector<std::string> get_required_extensions() const override;
    std::string get_name() const override
    {
        return TRACKER_NAME;
    }
    bool is_initialized() const override;

    // Get complete snapshot of controller state (inputs + poses)
    const ControllerSnapshot& get_snapshot(Hand hand) const;

protected:
    // Internal lifecycle methods - only accessible via friend classes
    friend class TeleopSession;

    std::shared_ptr<ITrackerImpl> initialize(const OpenXRSessionHandles& handles) override;

private:
    static constexpr const char* TRACKER_NAME = "ControllerTracker";
    // Implementation class declaration (Pimpl idiom)
    class Impl : public ITrackerImpl
    {
    public:
        explicit Impl(const OpenXRSessionHandles& handles);

        // Override from ITrackerImpl
        bool update(XrTime time) override;
        std::string get_name() const override
        {
            return ControllerTracker::TRACKER_NAME;
        }
        std::string get_schema_name() const override
        {
            return "";
        } // TODO: Add schema when available
        std::string get_schema_text() const override
        {
            return "";
        } // TODO: Add schema when available
        void serialize(flatbuffers::FlatBufferBuilder& builder, int64_t* out_timestamp = nullptr) const override;

        const ControllerSnapshot& get_snapshot(Hand hand) const;

    private:
        const OpenXRCoreFunctions core_funcs_;

        XrSession session_;
        XrSpace base_space_;

        // Paths for both hands
        XrPath left_hand_path_;
        XrPath right_hand_path_;

        // Actions - simplified to only the inputs we care about
        XrActionSetPtr action_set_;
        XrAction grip_pose_action_;
        XrAction aim_pose_action_;
        XrAction primary_click_action_;
        XrAction secondary_click_action_;
        XrAction thumbstick_action_;
        XrAction thumbstick_click_action_;
        XrAction squeeze_value_action_;
        XrAction trigger_value_action_;

        // Action spaces for both hands
        XrSpacePtr left_grip_space_;
        XrSpacePtr right_grip_space_;
        XrSpacePtr left_aim_space_;
        XrSpacePtr right_aim_space_;

        // Controller data for both hands
        ControllerSnapshot left_snapshot_;
        ControllerSnapshot right_snapshot_;
    };

    // Weak pointer to impl (owned by session)
    std::weak_ptr<Impl> cached_impl_;
};

} // namespace core
