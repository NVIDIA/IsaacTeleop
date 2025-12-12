// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include "tracker.hpp"

#include <array>
#include <deque>
#include <memory>
#include <mutex>

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

// Enum for all supported controller input components
// Maps to OpenXR input paths: /user/hand/{left|right}/input/{component}
enum class ControllerInput
{
    PrimaryClick = 0, // .../input/primary/click (e.g., X/A buttons)
    SecondaryClick, // .../input/secondary/click (e.g., Y/B buttons)
    ThumbstickX, // .../input/thumbstick/x
    ThumbstickY, // .../input/thumbstick/y
    ThumbstickClick, // .../input/thumbstick/click
    SqueezeValue, // .../input/squeeze/value
    TriggerValue, // .../input/trigger/value

    COUNT // Number of inputs (keep last)
};

// Helper to convert enum to array index
constexpr size_t to_index(ControllerInput input)
{
    return static_cast<size_t>(input);
}

// Convert input enum to string for debugging
inline const char* to_string(ControllerInput input)
{
    switch (input)
    {
    case ControllerInput::PrimaryClick:
        return "primary/click";
    case ControllerInput::SecondaryClick:
        return "secondary/click";
    case ControllerInput::ThumbstickX:
        return "thumbstick/x";
    case ControllerInput::ThumbstickY:
        return "thumbstick/y";
    case ControllerInput::ThumbstickClick:
        return "thumbstick/click";
    case ControllerInput::SqueezeValue:
        return "squeeze/value";
    case ControllerInput::TriggerValue:
        return "trigger/value";
    default:
        return "unknown";
    }
}

// Simple snapshot of all controller input states
// Used for snapshot mode - query current state at any time
struct ControllerInputState
{
    // All inputs stored in array, indexed by ControllerInput enum
    float values[static_cast<size_t>(ControllerInput::COUNT)];

    ControllerInputState()
    {
        for (size_t i = 0; i < static_cast<size_t>(ControllerInput::COUNT); ++i)
        {
            values[i] = 0.0f;
        }
    }

    // Get value by enum
    float get(ControllerInput input) const
    {
        return values[to_index(input)];
    }

    // Set value by enum
    void set(ControllerInput input, float value)
    {
        values[to_index(input)] = value;
    }

    // Array access operators for convenience
    float operator[](ControllerInput input) const
    {
        return values[to_index(input)];
    }

    float& operator[](ControllerInput input)
    {
        return values[to_index(input)];
    }

    // Equality operator for detecting state changes
    bool operator==(const ControllerInputState& other) const
    {
        for (size_t i = 0; i < static_cast<size_t>(ControllerInput::COUNT); ++i)
        {
            if (values[i] != other.values[i])
                return false;
        }
        return true;
    }

    bool operator!=(const ControllerInputState& other) const
    {
        return !(*this == other);
    }
};

// Controller pose data
struct ControllerPose
{
    float position[3]; // x, y, z in meters
    float orientation[4]; // x, y, z, w (quaternion)
    bool is_valid;

    ControllerPose() : position{ 0.0f, 0.0f, 0.0f }, orientation{ 0.0f, 0.0f, 0.0f, 1.0f }, is_valid(false)
    {
    }
};

// Snapshot data for a single controller (used in snapshot mode)
struct ControllerSnapshot
{
    ControllerPose grip_pose;
    ControllerPose aim_pose;
    ControllerInputState inputs;
    bool is_active;
    XrTime timestamp;

    ControllerSnapshot() : is_active(false), timestamp(0)
    {
    }
};

// Simple controller input event (used in event stream mode)
// An event is just an input component and its new value
struct ControllerInputEvent
{
    ControllerInput input;
    float value;
    XrTime timestamp;

    ControllerInputEvent(ControllerInput i, float v, XrTime t) : input(i), value(v), timestamp(t)
    {
    }
};

// Controller tracker - tracks both left and right controllers
// PUBLIC API: Only exposes query methods
// Supports two modes of data access:
// 1. Snapshot mode: Get current state (get_snapshot)
// 2. Event stream mode: Get individual input changes (get_events)
//
// Pose queries are separate and can be polled independently
class ControllerTracker : public ITracker
{
public:
    ControllerTracker();
    ~ControllerTracker() override;

    // Public API - what external users see
    std::vector<std::string> get_required_extensions() const override;
    std::string get_name() const override;
    bool is_initialized() const override;

    // === SNAPSHOT MODE ===
    // Get complete snapshot of controller state (inputs + pose)
    const ControllerSnapshot& get_snapshot(Hand hand) const;

    // === POSE QUERIES (separate from event stream) ===
    // Query pose directly - not affected by event queue
    const ControllerPose& get_grip_pose(Hand hand) const;
    const ControllerPose& get_aim_pose(Hand hand) const;

    // === EVENT STREAM MODE ===
    // Get all queued input events (clears the queue)
    std::vector<ControllerInputEvent> get_events(Hand hand);

    // Clear queued events
    void clear_events(Hand hand);

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

        const ControllerSnapshot& get_snapshot(Hand hand) const;
        const ControllerPose& get_grip_pose(Hand hand) const;
        const ControllerPose& get_aim_pose(Hand hand) const;

        // Event stream mode access
        std::vector<ControllerInputEvent> get_events(Hand hand);
        void clear_events(Hand hand);

    private:
        // Private constructor - only callable from factory function
        Impl(XrSession session,
             XrSpace base_space,
             XrActionSet action_set,
             XrAction grip_pose_action,
             XrAction aim_pose_action,
             XrAction primary_click_action,
             XrAction secondary_click_action,
             XrAction thumbstick_action,
             XrAction thumbstick_click_action,
             XrAction squeeze_value_action,
             XrAction trigger_value_action,
             XrSpace left_grip_space,
             XrSpace right_grip_space,
             XrSpace left_aim_space,
             XrSpace right_aim_space,
             XrPath left_hand_path,
             XrPath right_hand_path,
             const OpenXRCoreFunctions& core_funcs);

        // Helper functions
        void cleanup();
        void enqueue_event(Hand hand, ControllerInput input, float value, XrTime timestamp);

        XrSession session_;
        XrSpace base_space_;

        // Actions - simplified to only the inputs we care about
        XrActionSet action_set_;
        XrAction grip_pose_action_;
        XrAction aim_pose_action_;
        XrAction primary_click_action_;
        XrAction secondary_click_action_;
        XrAction thumbstick_action_;
        XrAction thumbstick_click_action_;
        XrAction squeeze_value_action_;
        XrAction trigger_value_action_;

        // Action spaces for both hands
        XrSpace left_grip_space_;
        XrSpace right_grip_space_;
        XrSpace left_aim_space_;
        XrSpace right_aim_space_;

        // Paths for both hands
        XrPath left_hand_path_;
        XrPath right_hand_path_;

        // Controller data for both hands
        ControllerSnapshot left_snapshot_;
        ControllerSnapshot right_snapshot_;

        // Previous state for detecting changes (event stream mode)
        ControllerInputState prev_left_inputs_;
        ControllerInputState prev_right_inputs_;

        // Event queues for event stream mode (thread-safe) - separate for each hand
        mutable std::mutex left_queue_mutex_;
        mutable std::mutex right_queue_mutex_;
        std::deque<ControllerInputEvent> left_event_queue_;
        std::deque<ControllerInputEvent> right_event_queue_;
        static constexpr size_t MAX_QUEUE_SIZE = 1000;

        // Core functions
        OpenXRCoreFunctions core_funcs_;
    };

    // Weak pointer to impl (owned by session)
    std::weak_ptr<Impl> cached_impl_;
};

} // namespace core
