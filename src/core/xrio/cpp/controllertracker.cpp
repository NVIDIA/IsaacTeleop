// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/xrio/controllertracker.hpp"

#include <cassert>
#include <cmath>
#include <cstring>
#include <iostream>

namespace core
{

namespace
{

// Helper functions for getting OpenXR action states with changedSinceLastSync tracking

float get_boolean_action_state(
    XrSession session, const OpenXRCoreFunctions& core_funcs, XrAction action, XrPath subaction_path, bool& changed)
{
    XrActionStateGetInfo get_info{ XR_TYPE_ACTION_STATE_GET_INFO };
    get_info.action = action;
    get_info.subactionPath = subaction_path;

    XrActionStateBoolean state{ XR_TYPE_ACTION_STATE_BOOLEAN };
    XrResult result = core_funcs.xrGetActionStateBoolean(session, &get_info, &state);
    if (XR_SUCCEEDED(result) && state.isActive)
    {
        changed = state.changedSinceLastSync;
        return state.currentState ? 1.0f : 0.0f;
    }
    changed = false;
    return 0.0f;
}

float get_float_action_state(
    XrSession session, const OpenXRCoreFunctions& core_funcs, XrAction action, XrPath subaction_path, bool& changed)
{
    XrActionStateGetInfo get_info{ XR_TYPE_ACTION_STATE_GET_INFO };
    get_info.action = action;
    get_info.subactionPath = subaction_path;

    XrActionStateFloat state{ XR_TYPE_ACTION_STATE_FLOAT };
    XrResult result = core_funcs.xrGetActionStateFloat(session, &get_info, &state);
    if (XR_SUCCEEDED(result) && state.isActive)
    {
        changed = state.changedSinceLastSync;
        return state.currentState;
    }
    changed = false;
    return 0.0f;
}

bool get_vector2_action_state(XrSession session,
                              const OpenXRCoreFunctions& core_funcs,
                              XrAction action,
                              XrPath subaction_path,
                              float& out_x,
                              float& out_y,
                              bool& changed)
{
    XrActionStateGetInfo get_info{ XR_TYPE_ACTION_STATE_GET_INFO };
    get_info.action = action;
    get_info.subactionPath = subaction_path;

    XrActionStateVector2f state{ XR_TYPE_ACTION_STATE_VECTOR2F };
    XrResult result = core_funcs.xrGetActionStateVector2f(session, &get_info, &state);
    if (XR_SUCCEEDED(result) && state.isActive)
    {
        out_x = state.currentState.x;
        out_y = state.currentState.y;
        changed = state.changedSinceLastSync;
        return true;
    }
    out_x = out_y = 0.0f;
    changed = false;
    return false;
}

} // anonymous namespace

// ============================================================================
// ControllerTracker::Impl Implementation
// ============================================================================

// Factory function for creating the Impl
std::unique_ptr<ControllerTracker::Impl> ControllerTracker::Impl::create(const OpenXRSessionHandles& handles)
{
    // Load core OpenXR functions dynamically using the provided xrGetInstanceProcAddr
    OpenXRCoreFunctions core_funcs;
    if (!core_funcs.load(handles.instance, handles.xrGetInstanceProcAddr))
    {
        std::cerr << "Failed to load core OpenXR functions for ControllerTracker" << std::endl;
        return nullptr;
    }

    // Create action set for both controllers
    XrActionSetCreateInfo action_set_info{ XR_TYPE_ACTION_SET_CREATE_INFO };
    strcpy(action_set_info.actionSetName, "controller_tracking");
    strcpy(action_set_info.localizedActionSetName, "Controller Tracking");
    action_set_info.priority = 0;

    XrActionSet action_set = XR_NULL_HANDLE;
    XrResult result = core_funcs.xrCreateActionSet(handles.instance, &action_set_info, &action_set);

    if (XR_FAILED(result))
    {
        std::cerr << "Failed to create controller action set: " << result << std::endl;
        return nullptr;
    }

    // Create hand paths for BOTH hands
    XrPath left_hand_path = XR_NULL_PATH;
    XrPath right_hand_path = XR_NULL_PATH;
    core_funcs.xrStringToPath(handles.instance, "/user/hand/left", &left_hand_path);
    core_funcs.xrStringToPath(handles.instance, "/user/hand/right", &right_hand_path);
    XrPath hand_paths[2] = { left_hand_path, right_hand_path };

    // Create actions with BOTH subaction paths
    auto create_action = [&](const char* name, const char* localized_name, XrActionType type, XrAction& out_action) -> bool
    {
        XrActionCreateInfo action_info{ XR_TYPE_ACTION_CREATE_INFO };
        action_info.actionType = type;
        strcpy(action_info.actionName, name);
        strcpy(action_info.localizedActionName, localized_name);
        action_info.countSubactionPaths = 2; // BOTH hands
        action_info.subactionPaths = hand_paths;

        result = core_funcs.xrCreateAction(action_set, &action_info, &out_action);
        if (XR_FAILED(result))
        {
            std::cerr << "Failed to create action " << name << ": " << result << std::endl;
            return false;
        }
        return true;
    };

    // Create all actions - only the ones we care about
    XrAction grip_pose_action = XR_NULL_HANDLE;
    XrAction aim_pose_action = XR_NULL_HANDLE;
    XrAction primary_click_action = XR_NULL_HANDLE;
    XrAction secondary_click_action = XR_NULL_HANDLE;
    XrAction thumbstick_action = XR_NULL_HANDLE;
    XrAction thumbstick_click_action = XR_NULL_HANDLE;
    XrAction squeeze_value_action = XR_NULL_HANDLE;
    XrAction trigger_value_action = XR_NULL_HANDLE;

    if (!create_action("grip_pose", "Grip Pose", XR_ACTION_TYPE_POSE_INPUT, grip_pose_action) ||
        !create_action("aim_pose", "Aim Pose", XR_ACTION_TYPE_POSE_INPUT, aim_pose_action) ||
        !create_action("primary_click", "Primary Click", XR_ACTION_TYPE_BOOLEAN_INPUT, primary_click_action) ||
        !create_action("secondary_click", "Secondary Click", XR_ACTION_TYPE_BOOLEAN_INPUT, secondary_click_action) ||
        !create_action("thumbstick", "Thumbstick", XR_ACTION_TYPE_VECTOR2F_INPUT, thumbstick_action) ||
        !create_action("thumbstick_click", "Thumbstick Click", XR_ACTION_TYPE_BOOLEAN_INPUT, thumbstick_click_action) ||
        !create_action("squeeze_value", "Squeeze Value", XR_ACTION_TYPE_FLOAT_INPUT, squeeze_value_action) ||
        !create_action("trigger_value", "Trigger Value", XR_ACTION_TYPE_FLOAT_INPUT, trigger_value_action))
    {
        core_funcs.xrDestroyActionSet(action_set);
        return nullptr;
    }

    // Suggest bindings for Oculus Touch controller profile
    XrPath interaction_profile_path;
    core_funcs.xrStringToPath(
        handles.instance, "/interaction_profiles/oculus/touch_controller", &interaction_profile_path);

    std::vector<XrActionSuggestedBinding> bindings;
    auto add_binding = [&](XrAction action, const char* path)
    {
        XrPath binding_path;
        if (XR_SUCCEEDED(core_funcs.xrStringToPath(handles.instance, path, &binding_path)))
        {
            bindings.push_back({ action, binding_path });
        }
    };

    // Common bindings for both hands
    add_binding(grip_pose_action, "/user/hand/left/input/grip/pose");
    add_binding(grip_pose_action, "/user/hand/right/input/grip/pose");
    add_binding(aim_pose_action, "/user/hand/left/input/aim/pose");
    add_binding(aim_pose_action, "/user/hand/right/input/aim/pose");
    add_binding(thumbstick_action, "/user/hand/left/input/thumbstick");
    add_binding(thumbstick_action, "/user/hand/right/input/thumbstick");
    add_binding(thumbstick_click_action, "/user/hand/left/input/thumbstick/click");
    add_binding(thumbstick_click_action, "/user/hand/right/input/thumbstick/click");
    add_binding(squeeze_value_action, "/user/hand/left/input/squeeze/value");
    add_binding(squeeze_value_action, "/user/hand/right/input/squeeze/value");
    add_binding(trigger_value_action, "/user/hand/left/input/trigger/value");
    add_binding(trigger_value_action, "/user/hand/right/input/trigger/value");

    // Hand-specific button bindings
    add_binding(primary_click_action, "/user/hand/left/input/x/click"); // Left: X
    add_binding(secondary_click_action, "/user/hand/left/input/y/click"); // Left: Y
    add_binding(primary_click_action, "/user/hand/right/input/a/click"); // Right: A
    add_binding(secondary_click_action, "/user/hand/right/input/b/click"); // Right: B

    XrInteractionProfileSuggestedBinding suggested_bindings{ XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING };
    suggested_bindings.interactionProfile = interaction_profile_path;
    suggested_bindings.countSuggestedBindings = static_cast<uint32_t>(bindings.size());
    suggested_bindings.suggestedBindings = bindings.data();

    result = core_funcs.xrSuggestInteractionProfileBindings(handles.instance, &suggested_bindings);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to suggest interaction profile bindings: " << result << std::endl;
        core_funcs.xrDestroyActionSet(action_set);
        return nullptr;
    }

    std::cout << "ControllerTracker: Using Oculus Touch Controller profile" << std::endl;

    // Attach action set to session
    XrSessionActionSetsAttachInfo attach_info{ XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO };
    attach_info.countActionSets = 1;
    attach_info.actionSets = &action_set;

    result = core_funcs.xrAttachSessionActionSets(handles.session, &attach_info);
    if (XR_FAILED(result))
    {
        std::cerr << "Failed to attach action sets: " << result << std::endl;
        core_funcs.xrDestroyActionSet(action_set);
        return nullptr;
    }

    // Create action spaces for both hands
    auto create_space = [&](XrAction action, XrPath subaction_path, XrSpace& out_space) -> bool
    {
        XrActionSpaceCreateInfo space_info{ XR_TYPE_ACTION_SPACE_CREATE_INFO };
        space_info.action = action;
        space_info.subactionPath = subaction_path;
        space_info.poseInActionSpace.orientation = { 0.0f, 0.0f, 0.0f, 1.0f };
        space_info.poseInActionSpace.position = { 0.0f, 0.0f, 0.0f };

        result = core_funcs.xrCreateActionSpace(handles.session, &space_info, &out_space);
        if (XR_FAILED(result))
        {
            std::cerr << "Failed to create action space: " << result << std::endl;
            return false;
        }
        return true;
    };

    XrSpace left_grip_space = XR_NULL_HANDLE;
    XrSpace right_grip_space = XR_NULL_HANDLE;
    XrSpace left_aim_space = XR_NULL_HANDLE;
    XrSpace right_aim_space = XR_NULL_HANDLE;

    if (!create_space(grip_pose_action, left_hand_path, left_grip_space) ||
        !create_space(grip_pose_action, right_hand_path, right_grip_space) ||
        !create_space(aim_pose_action, left_hand_path, left_aim_space) ||
        !create_space(aim_pose_action, right_hand_path, right_aim_space))
    {
        if (left_grip_space != XR_NULL_HANDLE)
            core_funcs.xrDestroySpace(left_grip_space);
        if (right_grip_space != XR_NULL_HANDLE)
            core_funcs.xrDestroySpace(right_grip_space);
        if (left_aim_space != XR_NULL_HANDLE)
            core_funcs.xrDestroySpace(left_aim_space);
        if (right_aim_space != XR_NULL_HANDLE)
            core_funcs.xrDestroySpace(right_aim_space);
        core_funcs.xrDestroyActionSet(action_set);
        return nullptr;
    }

    std::cout << "ControllerTracker initialized (left + right)" << std::endl;

    // Create the Impl using private constructor
    try
    {
        return std::unique_ptr<Impl>(new Impl(handles.session, handles.space, action_set, grip_pose_action,
                                              aim_pose_action, primary_click_action, secondary_click_action,
                                              thumbstick_action, thumbstick_click_action, squeeze_value_action,
                                              trigger_value_action, left_grip_space, right_grip_space, left_aim_space,
                                              right_aim_space, left_hand_path, right_hand_path, core_funcs));
    }
    catch (...)
    {
        // Clean up on construction failure
        core_funcs.xrDestroySpace(left_grip_space);
        core_funcs.xrDestroySpace(right_grip_space);
        core_funcs.xrDestroySpace(left_aim_space);
        core_funcs.xrDestroySpace(right_aim_space);
        core_funcs.xrDestroyActionSet(action_set);
        throw;
    }
}

ControllerTracker::Impl::~Impl()
{
    cleanup();
}

// Private constructor
ControllerTracker::Impl::Impl(XrSession session,
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
                              const OpenXRCoreFunctions& core_funcs)
    : session_(session),
      base_space_(base_space),
      action_set_(action_set),
      grip_pose_action_(grip_pose_action),
      aim_pose_action_(aim_pose_action),
      primary_click_action_(primary_click_action),
      secondary_click_action_(secondary_click_action),
      thumbstick_action_(thumbstick_action),
      thumbstick_click_action_(thumbstick_click_action),
      squeeze_value_action_(squeeze_value_action),
      trigger_value_action_(trigger_value_action),
      left_grip_space_(left_grip_space),
      right_grip_space_(right_grip_space),
      left_aim_space_(left_aim_space),
      right_aim_space_(right_aim_space),
      left_hand_path_(left_hand_path),
      right_hand_path_(right_hand_path),
      core_funcs_(core_funcs)
{
}

void ControllerTracker::Impl::cleanup()
{
    if (left_grip_space_ != XR_NULL_HANDLE)
    {
        core_funcs_.xrDestroySpace(left_grip_space_);
        left_grip_space_ = XR_NULL_HANDLE;
    }
    if (right_grip_space_ != XR_NULL_HANDLE)
    {
        core_funcs_.xrDestroySpace(right_grip_space_);
        right_grip_space_ = XR_NULL_HANDLE;
    }
    if (left_aim_space_ != XR_NULL_HANDLE)
    {
        core_funcs_.xrDestroySpace(left_aim_space_);
        left_aim_space_ = XR_NULL_HANDLE;
    }
    if (right_aim_space_ != XR_NULL_HANDLE)
    {
        core_funcs_.xrDestroySpace(right_aim_space_);
        right_aim_space_ = XR_NULL_HANDLE;
    }
    if (action_set_ != XR_NULL_HANDLE)
    {
        core_funcs_.xrDestroyActionSet(action_set_);
        action_set_ = XR_NULL_HANDLE;
    }
}

// Override from ITrackerImpl
bool ControllerTracker::Impl::update(XrTime time)
{
    // Sync actions
    XrActionsSyncInfo sync_info{ XR_TYPE_ACTIONS_SYNC_INFO };
    XrActiveActionSet active_action_set{ action_set_, XR_NULL_PATH };
    sync_info.countActiveActionSets = 1;
    sync_info.activeActionSets = &active_action_set;

    XrResult result = core_funcs_.xrSyncActions(session_, &sync_info);
    if (XR_FAILED(result))
    {
        std::cerr << "[ControllerTracker] xrSyncActions failed: " << result << std::endl;
        return false;
    }

    // Helper to update a single controller
    auto update_controller = [&](XrPath hand_path, XrSpace grip_space, XrSpace aim_space, ControllerSnapshot& snapshot,
                                 ControllerInputState& prev_inputs, Hand hand)
    {
        // Update poses
        XrSpaceLocation grip_location{ XR_TYPE_SPACE_LOCATION };
        result = core_funcs_.xrLocateSpace(grip_space, base_space_, time, &grip_location);
        if (XR_SUCCEEDED(result))
        {
            snapshot.grip_pose.is_valid = (grip_location.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) &&
                                          (grip_location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT);
            if (snapshot.grip_pose.is_valid)
            {
                snapshot.grip_pose.position[0] = grip_location.pose.position.x;
                snapshot.grip_pose.position[1] = grip_location.pose.position.y;
                snapshot.grip_pose.position[2] = grip_location.pose.position.z;
                snapshot.grip_pose.orientation[0] = grip_location.pose.orientation.x;
                snapshot.grip_pose.orientation[1] = grip_location.pose.orientation.y;
                snapshot.grip_pose.orientation[2] = grip_location.pose.orientation.z;
                snapshot.grip_pose.orientation[3] = grip_location.pose.orientation.w;
            }
        }

        XrSpaceLocation aim_location{ XR_TYPE_SPACE_LOCATION };
        result = core_funcs_.xrLocateSpace(aim_space, base_space_, time, &aim_location);
        if (XR_SUCCEEDED(result))
        {
            snapshot.aim_pose.is_valid = (aim_location.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) &&
                                         (aim_location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT);
            if (snapshot.aim_pose.is_valid)
            {
                snapshot.aim_pose.position[0] = aim_location.pose.position.x;
                snapshot.aim_pose.position[1] = aim_location.pose.position.y;
                snapshot.aim_pose.position[2] = aim_location.pose.position.z;
                snapshot.aim_pose.orientation[0] = aim_location.pose.orientation.x;
                snapshot.aim_pose.orientation[1] = aim_location.pose.orientation.y;
                snapshot.aim_pose.orientation[2] = aim_location.pose.orientation.z;
                snapshot.aim_pose.orientation[3] = aim_location.pose.orientation.w;
            }
        }

        snapshot.is_active = snapshot.grip_pose.is_valid || snapshot.aim_pose.is_valid;
        snapshot.timestamp = time;

        // Update all input values and track which ones changed via changedSinceLastSync
        ControllerInputState current_inputs;
        bool changed[static_cast<size_t>(ControllerInput::COUNT)] = { false };

        current_inputs[ControllerInput::PrimaryClick] = get_boolean_action_state(
            session_, core_funcs_, primary_click_action_, hand_path, changed[to_index(ControllerInput::PrimaryClick)]);
        current_inputs[ControllerInput::SecondaryClick] =
            get_boolean_action_state(session_, core_funcs_, secondary_click_action_, hand_path,
                                     changed[to_index(ControllerInput::SecondaryClick)]);

        bool thumbstick_changed = false;
        get_vector2_action_state(session_, core_funcs_, thumbstick_action_, hand_path,
                                 current_inputs.values[to_index(ControllerInput::ThumbstickX)],
                                 current_inputs.values[to_index(ControllerInput::ThumbstickY)], thumbstick_changed);
        // Both X and Y share the same changed flag from the vector2 action
        changed[to_index(ControllerInput::ThumbstickX)] = thumbstick_changed;
        changed[to_index(ControllerInput::ThumbstickY)] = thumbstick_changed;

        current_inputs[ControllerInput::ThumbstickClick] =
            get_boolean_action_state(session_, core_funcs_, thumbstick_click_action_, hand_path,
                                     changed[to_index(ControllerInput::ThumbstickClick)]);
        current_inputs[ControllerInput::SqueezeValue] = get_float_action_state(
            session_, core_funcs_, squeeze_value_action_, hand_path, changed[to_index(ControllerInput::SqueezeValue)]);
        current_inputs[ControllerInput::TriggerValue] = get_float_action_state(
            session_, core_funcs_, trigger_value_action_, hand_path, changed[to_index(ControllerInput::TriggerValue)]);

        // Only queue events for inputs that actually changed according to OpenXR
        // This reduces false positives and ensures we don't miss real changes
        for (size_t i = 0; i < static_cast<size_t>(ControllerInput::COUNT); ++i)
        {
            if (changed[i] && current_inputs.values[i] != prev_inputs.values[i])
            {
                enqueue_event(hand, static_cast<ControllerInput>(i), current_inputs.values[i], time);
            }
        }

        // Update current state
        snapshot.inputs = current_inputs;
        prev_inputs = current_inputs;
    };

    // Update both controllers
    update_controller(left_hand_path_, left_grip_space_, left_aim_space_, left_snapshot_, prev_left_inputs_, Hand::Left);
    update_controller(
        right_hand_path_, right_grip_space_, right_aim_space_, right_snapshot_, prev_right_inputs_, Hand::Right);

    return left_snapshot_.is_active || right_snapshot_.is_active;
}

void ControllerTracker::Impl::enqueue_event(Hand hand, ControllerInput input, float value, XrTime timestamp)
{
    auto& queue = (hand == Hand::Left) ? left_event_queue_ : right_event_queue_;
    auto& mutex = (hand == Hand::Left) ? left_queue_mutex_ : right_queue_mutex_;

    std::lock_guard<std::mutex> lock(mutex);

    // If queue is full, drop the oldest event
    if (queue.size() >= MAX_QUEUE_SIZE)
    {
        queue.pop_front();
    }

    queue.emplace_back(input, value, timestamp);
}

const ControllerSnapshot& ControllerTracker::Impl::get_snapshot(Hand hand) const
{
    return (hand == Hand::Left) ? left_snapshot_ : right_snapshot_;
}

const ControllerPose& ControllerTracker::Impl::get_grip_pose(Hand hand) const
{
    return (hand == Hand::Left) ? left_snapshot_.grip_pose : right_snapshot_.grip_pose;
}

const ControllerPose& ControllerTracker::Impl::get_aim_pose(Hand hand) const
{
    return (hand == Hand::Left) ? left_snapshot_.aim_pose : right_snapshot_.aim_pose;
}

std::vector<ControllerInputEvent> ControllerTracker::Impl::get_events(Hand hand)
{
    auto& queue = (hand == Hand::Left) ? left_event_queue_ : right_event_queue_;
    auto& mutex = (hand == Hand::Left) ? left_queue_mutex_ : right_queue_mutex_;

    std::lock_guard<std::mutex> lock(mutex);
    std::vector<ControllerInputEvent> events(queue.begin(), queue.end());
    queue.clear();
    return events;
}

void ControllerTracker::Impl::clear_events(Hand hand)
{
    auto& queue = (hand == Hand::Left) ? left_event_queue_ : right_event_queue_;
    auto& mutex = (hand == Hand::Left) ? left_queue_mutex_ : right_queue_mutex_;

    std::lock_guard<std::mutex> lock(mutex);
    queue.clear();
}

// ============================================================================
// ControllerTracker Public Interface Implementation
// ============================================================================

ControllerTracker::ControllerTracker()
{
}

ControllerTracker::~ControllerTracker()
{
    // Session owns the impl, weak_ptr will detect if it's destroyed
}

std::vector<std::string> ControllerTracker::get_required_extensions() const
{
    // Controllers don't require any extensions (they're part of core OpenXR)
    return {};
}

std::string ControllerTracker::get_name() const
{
    return "ControllerTracker";
}

const ControllerSnapshot& ControllerTracker::get_snapshot(Hand hand) const
{
    static const ControllerSnapshot empty_snapshot{};
    auto impl = cached_impl_.lock();
    if (!impl)
        return empty_snapshot;
    return impl->get_snapshot(hand);
}

const ControllerPose& ControllerTracker::get_grip_pose(Hand hand) const
{
    static const ControllerPose empty_pose{};
    auto impl = cached_impl_.lock();
    if (!impl)
        return empty_pose;
    return impl->get_grip_pose(hand);
}

const ControllerPose& ControllerTracker::get_aim_pose(Hand hand) const
{
    static const ControllerPose empty_pose{};
    auto impl = cached_impl_.lock();
    if (!impl)
        return empty_pose;
    return impl->get_aim_pose(hand);
}

std::vector<ControllerInputEvent> ControllerTracker::get_events(Hand hand)
{
    auto impl = cached_impl_.lock();
    if (!impl)
        return {};
    return impl->get_events(hand);
}

void ControllerTracker::clear_events(Hand hand)
{
    auto impl = cached_impl_.lock();
    if (!impl)
        return;
    impl->clear_events(hand);
}

std::shared_ptr<ITrackerImpl> ControllerTracker::initialize(const OpenXRSessionHandles& handles)
{
    auto impl = Impl::create(handles);
    if (impl)
    {
        // We need to convert unique_ptr to shared_ptr to use weak_ptr
        // The session will own it, so we create a shared_ptr and cache a weak_ptr
        auto shared = std::shared_ptr<Impl>(impl.release());
        cached_impl_ = shared;
        return shared;
    }
    return nullptr;
}

bool ControllerTracker::is_initialized() const
{
    return !cached_impl_.expired();
}

} // namespace core
