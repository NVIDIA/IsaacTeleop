// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "inc/deviceio/controller_tracker.hpp"

#include "inc/deviceio/deviceio_session.hpp"

#include <cassert>
#include <cmath>
#include <cstring>
#include <iostream>
#include <stdexcept>
#include <unordered_map>

namespace core
{

namespace
{

// Helper functions for getting OpenXR action states

XrPath xr_path_from_string(const OpenXRCoreFunctions& funcs, XrInstance instance, const char* s)
{
    XrPath path = XR_NULL_PATH;
    XrResult res = funcs.xrStringToPath(instance, s, &path);
    if (XR_FAILED(res))
    {
        throw std::runtime_error(std::string("xrStringToPath failed for '") + s + "': " + std::to_string(res));
    }
    return path;
}

bool get_boolean_action_state(XrSession session, const OpenXRCoreFunctions& core_funcs, XrAction action, XrPath subaction_path)
{
    XrActionStateGetInfo get_info{ XR_TYPE_ACTION_STATE_GET_INFO };
    get_info.action = action;
    get_info.subactionPath = subaction_path;

    XrActionStateBoolean state{ XR_TYPE_ACTION_STATE_BOOLEAN };
    XrResult result = core_funcs.xrGetActionStateBoolean(session, &get_info, &state);
    if (XR_SUCCEEDED(result) && state.isActive)
    {
        return state.currentState;
    }
    return false;
}

float get_float_action_state(XrSession session, const OpenXRCoreFunctions& core_funcs, XrAction action, XrPath subaction_path)
{
    XrActionStateGetInfo get_info{ XR_TYPE_ACTION_STATE_GET_INFO };
    get_info.action = action;
    get_info.subactionPath = subaction_path;

    XrActionStateFloat state{ XR_TYPE_ACTION_STATE_FLOAT };
    XrResult result = core_funcs.xrGetActionStateFloat(session, &get_info, &state);
    if (XR_SUCCEEDED(result) && state.isActive)
    {
        return state.currentState;
    }
    return 0.0f;
}

bool get_vector2_action_state(XrSession session,
                              const OpenXRCoreFunctions& core_funcs,
                              XrAction action,
                              XrPath subaction_path,
                              float& out_x,
                              float& out_y)
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
        return true;
    }
    out_x = out_y = 0.0f;
    return false;
}

XrSpacePtr create_space(const OpenXRCoreFunctions& funcs, XrSession session, XrAction action, XrPath subaction_path)
{
    assert(action != XR_NULL_HANDLE);
    assert(subaction_path != XR_NULL_PATH);

    XrActionSpaceCreateInfo space_info{ XR_TYPE_ACTION_SPACE_CREATE_INFO };
    space_info.action = action;
    space_info.subactionPath = subaction_path;
    space_info.poseInActionSpace.orientation = { 0.0f, 0.0f, 0.0f, 1.0f };
    space_info.poseInActionSpace.position = { 0.0f, 0.0f, 0.0f };

    return createActionSpace(funcs, session, &space_info);
};

XrAction create_action(const OpenXRCoreFunctions& funcs,
                       XrActionSet action_set,
                       XrPath left_hand_path,
                       XrPath right_hand_path,
                       const char* name,
                       const char* localized_name,
                       XrActionType type)
{
    XrAction out_action;

    XrPath hand_paths[2] = { left_hand_path, right_hand_path };

    XrActionCreateInfo action_info{ XR_TYPE_ACTION_CREATE_INFO };
    action_info.actionType = type;
    strcpy(action_info.actionName, name);
    strcpy(action_info.localizedActionName, localized_name);
    action_info.countSubactionPaths = 2; // BOTH hands
    action_info.subactionPaths = hand_paths;

    XrResult res = funcs.xrCreateAction(action_set, &action_info, &out_action);
    if (XR_FAILED(res))
    {
        throw std::runtime_error(std::string("Failed to create action ") + name + ": " + std::to_string(res));
    }

    return out_action;
};

} // anonymous namespace

// ============================================================================
// ControllerTracker::Impl Implementation
// ============================================================================

// Constructor - throws std::runtime_error on failure
ControllerTracker::Impl::Impl(const OpenXRSessionHandles& handles)
    : core_funcs_(OpenXRCoreFunctions::load(handles.instance, handles.xrGetInstanceProcAddr)),
      session_(handles.session),
      base_space_(handles.space),

      left_hand_path_(xr_path_from_string(core_funcs_, handles.instance, "/user/hand/left")),
      right_hand_path_(xr_path_from_string(core_funcs_, handles.instance, "/user/hand/right")),

      action_set_(createActionSet(core_funcs_,
                                  handles.instance,
                                  { .type = XR_TYPE_ACTION_SET_CREATE_INFO,
                                    .actionSetName = "controller_tracking",
                                    .localizedActionSetName = "Controller Tracking" })),
      grip_pose_action_(create_action(core_funcs_,
                                      action_set_.get(),
                                      left_hand_path_,
                                      right_hand_path_,
                                      "grip_pose",
                                      "Grip Pose",
                                      XR_ACTION_TYPE_POSE_INPUT)),
      aim_pose_action_(create_action(
          core_funcs_, action_set_.get(), left_hand_path_, right_hand_path_, "aim_pose", "Aim Pose", XR_ACTION_TYPE_POSE_INPUT)),
      primary_click_action_(create_action(core_funcs_,
                                          action_set_.get(),
                                          left_hand_path_,
                                          right_hand_path_,
                                          "primary_click",
                                          "Primary Click",
                                          XR_ACTION_TYPE_BOOLEAN_INPUT)),
      secondary_click_action_(create_action(core_funcs_,
                                            action_set_.get(),
                                            left_hand_path_,
                                            right_hand_path_,
                                            "secondary_click",
                                            "Secondary Click",
                                            XR_ACTION_TYPE_BOOLEAN_INPUT)),
      thumbstick_action_(create_action(core_funcs_,
                                       action_set_.get(),
                                       left_hand_path_,
                                       right_hand_path_,
                                       "thumbstick",
                                       "Thumbstick",
                                       XR_ACTION_TYPE_VECTOR2F_INPUT)),
      thumbstick_click_action_(create_action(core_funcs_,
                                             action_set_.get(),
                                             left_hand_path_,
                                             right_hand_path_,
                                             "thumbstick_click",
                                             "Thumbstick Click",
                                             XR_ACTION_TYPE_BOOLEAN_INPUT)),
      squeeze_value_action_(create_action(core_funcs_,
                                          action_set_.get(),
                                          left_hand_path_,
                                          right_hand_path_,
                                          "squeeze_value",
                                          "Squeeze Value",
                                          XR_ACTION_TYPE_FLOAT_INPUT)),
      trigger_value_action_(create_action(core_funcs_,
                                          action_set_.get(),
                                          left_hand_path_,
                                          right_hand_path_,
                                          "trigger_value",
                                          "Trigger Value",
                                          XR_ACTION_TYPE_FLOAT_INPUT)),

      left_grip_space_(create_space(core_funcs_, session_, grip_pose_action_, left_hand_path_)),
      right_grip_space_(create_space(core_funcs_, session_, grip_pose_action_, right_hand_path_)),
      left_aim_space_(create_space(core_funcs_, session_, aim_pose_action_, left_hand_path_)),
      right_aim_space_(create_space(core_funcs_, session_, aim_pose_action_, right_hand_path_))
{
    std::vector<XrActionSuggestedBinding> bindings;
    auto add_binding = [&](XrAction action, const char* path)
    {
        XrPath binding_path;
        if (XR_SUCCEEDED(core_funcs_.xrStringToPath(handles.instance, path, &binding_path)))
        {
            bindings.push_back({ action, binding_path });
        }
    };

    // Common bindings for both hands
    add_binding(grip_pose_action_, "/user/hand/left/input/grip/pose");
    add_binding(grip_pose_action_, "/user/hand/right/input/grip/pose");
    add_binding(aim_pose_action_, "/user/hand/left/input/aim/pose");
    add_binding(aim_pose_action_, "/user/hand/right/input/aim/pose");
    add_binding(thumbstick_action_, "/user/hand/left/input/thumbstick");
    add_binding(thumbstick_action_, "/user/hand/right/input/thumbstick");
    add_binding(thumbstick_click_action_, "/user/hand/left/input/thumbstick/click");
    add_binding(thumbstick_click_action_, "/user/hand/right/input/thumbstick/click");
    add_binding(squeeze_value_action_, "/user/hand/left/input/squeeze/value");
    add_binding(squeeze_value_action_, "/user/hand/right/input/squeeze/value");
    add_binding(trigger_value_action_, "/user/hand/left/input/trigger/value");
    add_binding(trigger_value_action_, "/user/hand/right/input/trigger/value");

    // Hand-specific button bindings
    add_binding(primary_click_action_, "/user/hand/left/input/x/click"); // Left: X
    add_binding(secondary_click_action_, "/user/hand/left/input/y/click"); // Left: Y
    add_binding(primary_click_action_, "/user/hand/right/input/a/click"); // Right: A
    add_binding(secondary_click_action_, "/user/hand/right/input/b/click"); // Right: B

    // Suggest bindings for Oculus Touch controller profile
    XrInteractionProfileSuggestedBinding suggested_bindings{ XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING };
    suggested_bindings.interactionProfile =
        xr_path_from_string(core_funcs_, handles.instance, "/interaction_profiles/oculus/touch_controller");
    suggested_bindings.countSuggestedBindings = static_cast<uint32_t>(bindings.size());
    suggested_bindings.suggestedBindings = bindings.data();

    XrResult result = core_funcs_.xrSuggestInteractionProfileBindings(handles.instance, &suggested_bindings);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to suggest interaction profile bindings: " + std::to_string(result));
    }

    std::cout << "ControllerTracker: Using Oculus Touch Controller profile" << std::endl;

    // Attach action set to session
    XrActionSet action_set_handle = action_set_.get();
    XrSessionActionSetsAttachInfo attach_info{ XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO };
    attach_info.countActionSets = 1;
    attach_info.actionSets = &action_set_handle;

    result = core_funcs_.xrAttachSessionActionSets(handles.session, &attach_info);
    if (XR_FAILED(result))
    {
        throw std::runtime_error("Failed to attach action sets: " + std::to_string(result));
    }

    std::cout << "ControllerTracker initialized (left + right)" << std::endl;
}

// Override from ITrackerImpl
bool ControllerTracker::Impl::update(XrTime time)
{
    last_update_time_ = time;

    // Sync actions
    XrActionsSyncInfo sync_info{ XR_TYPE_ACTIONS_SYNC_INFO };
    XrActiveActionSet active_action_set{ action_set_.get(), XR_NULL_PATH };
    sync_info.countActiveActionSets = 1;
    sync_info.activeActionSets = &active_action_set;

    XrResult result = core_funcs_.xrSyncActions(session_, &sync_info);
    if (XR_FAILED(result))
    {
        std::cerr << "[ControllerTracker] xrSyncActions failed: " << result << std::endl;
        return false;
    }

    auto update_controller = [&](XrPath hand_path, const XrSpacePtr& grip_space, const XrSpacePtr& aim_space,
                                 ControllerSnapshotTrackedT& tracked)
    {
        ControllerPose grip_pose{};
        ControllerPose aim_pose{};
        ControllerInputState inputs{};
        Timestamp timestamp{};

        // Update grip pose
        XrSpaceLocation grip_location{ XR_TYPE_SPACE_LOCATION };
        result = core_funcs_.xrLocateSpace(grip_space.get(), base_space_, time, &grip_location);
        if (XR_SUCCEEDED(result))
        {
            bool is_valid = (grip_location.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) &&
                            (grip_location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT);

            Point position(grip_location.pose.position.x, grip_location.pose.position.y, grip_location.pose.position.z);
            Quaternion orientation(grip_location.pose.orientation.x, grip_location.pose.orientation.y,
                                   grip_location.pose.orientation.z, grip_location.pose.orientation.w);
            Pose pose(position, orientation);
            grip_pose = ControllerPose(pose, is_valid);
        }

        // Update aim pose
        XrSpaceLocation aim_location{ XR_TYPE_SPACE_LOCATION };
        result = core_funcs_.xrLocateSpace(aim_space.get(), base_space_, time, &aim_location);
        if (XR_SUCCEEDED(result))
        {
            bool is_valid = (aim_location.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) &&
                            (aim_location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT);

            Point position(aim_location.pose.position.x, aim_location.pose.position.y, aim_location.pose.position.z);
            Quaternion orientation(aim_location.pose.orientation.x, aim_location.pose.orientation.y,
                                   aim_location.pose.orientation.z, aim_location.pose.orientation.w);
            Pose pose(position, orientation);
            aim_pose = ControllerPose(pose, is_valid);
        }

        bool is_active = grip_pose.is_valid() || aim_pose.is_valid();
        timestamp = Timestamp(time, time);

        // Update input values
        bool primary_click = get_boolean_action_state(session_, core_funcs_, primary_click_action_, hand_path);
        bool secondary_click = get_boolean_action_state(session_, core_funcs_, secondary_click_action_, hand_path);

        float thumbstick_x = 0.0f, thumbstick_y = 0.0f;
        get_vector2_action_state(session_, core_funcs_, thumbstick_action_, hand_path, thumbstick_x, thumbstick_y);

        bool thumbstick_click = get_boolean_action_state(session_, core_funcs_, thumbstick_click_action_, hand_path);
        float squeeze_value = get_float_action_state(session_, core_funcs_, squeeze_value_action_, hand_path);
        float trigger_value = get_float_action_state(session_, core_funcs_, trigger_value_action_, hand_path);

        inputs = ControllerInputState(
            primary_click, secondary_click, thumbstick_click, thumbstick_x, thumbstick_y, squeeze_value, trigger_value);

        if (is_active)
        {
            if (!tracked.data)
            {
                tracked.data = std::make_shared<ControllerSnapshotT>();
            }
            tracked.data->grip_pose = std::make_shared<ControllerPose>(grip_pose);
            tracked.data->aim_pose = std::make_shared<ControllerPose>(aim_pose);
            tracked.data->inputs = std::make_shared<ControllerInputState>(inputs);
            tracked.data->timestamp = std::make_shared<Timestamp>(timestamp);
        }
        else
        {
            tracked.data.reset();
        }
    };

    update_controller(left_hand_path_, left_grip_space_, left_aim_space_, left_tracked_);
    update_controller(right_hand_path_, right_grip_space_, right_aim_space_, right_tracked_);

    return left_tracked_.data || right_tracked_.data;
}

const ControllerSnapshotTrackedT& ControllerTracker::Impl::get_left_controller() const
{
    return left_tracked_;
}

const ControllerSnapshotTrackedT& ControllerTracker::Impl::get_right_controller() const
{
    return right_tracked_;
}

Timestamp ControllerTracker::Impl::serialize(flatbuffers::FlatBufferBuilder& builder, size_t channel_index) const
{
    if (channel_index > 1)
    {
        throw std::runtime_error("ControllerTracker::serialize: invalid channel_index " +
                                 std::to_string(channel_index) + " (must be 0 or 1)");
    }
    const auto& tracked = (channel_index == 0) ? left_tracked_ : right_tracked_;

    if (tracked.data)
    {
        auto data_offset = ControllerSnapshot::Pack(builder, tracked.data.get());
        ControllerSnapshotRecordBuilder record_builder(builder);
        record_builder.add_data(data_offset);
        builder.Finish(record_builder.Finish());
        return *tracked.data->timestamp;
    }
    ControllerSnapshotRecordBuilder record_builder(builder);
    builder.Finish(record_builder.Finish());
    return Timestamp(last_update_time_, last_update_time_);
}

// ============================================================================
// ControllerTracker Public Interface Implementation
// ============================================================================

std::vector<std::string> ControllerTracker::get_required_extensions() const
{
    // Controllers don't require any extensions (they're part of core OpenXR)
    return {};
}

const ControllerSnapshotTrackedT& ControllerTracker::get_left_controller(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_left_controller();
}

const ControllerSnapshotTrackedT& ControllerTracker::get_right_controller(const DeviceIOSession& session) const
{
    return static_cast<const Impl&>(session.get_tracker_impl(*this)).get_right_controller();
}

std::shared_ptr<ITrackerImpl> ControllerTracker::create_tracker(const OpenXRSessionHandles& handles) const
{
    // Multiple ControllerTracker instances sharing the same XrSession must reuse
    // a single Impl because OpenXR forbids duplicate action-set names /
    // interaction-profile bindings per session.
    static std::unordered_map<XrSession, std::weak_ptr<ITrackerImpl>> shared_impls;

    // Prune expired entries while we're here
    for (auto it = shared_impls.begin(); it != shared_impls.end();)
    {
        if (it->second.expired())
            it = shared_impls.erase(it);
        else
            ++it;
    }

    auto& weak = shared_impls[handles.session];
    if (auto existing = weak.lock())
    {
        std::cout << "ControllerTracker: Reusing existing impl for this XrSession" << std::endl;
        return existing;
    }

    auto impl = std::make_shared<Impl>(handles);
    weak = impl;
    return impl;
}

} // namespace core
