// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Controller input tracking

#include <plugin_utils/controllers.hpp>

#include <cstring>
#include <iostream>
#include <stdexcept>
#include <vector>

namespace plugin_utils
{

namespace
{
void CheckXrResult(XrResult result, const char* message)
{
    if (XR_FAILED(result))
    {
        throw std::runtime_error(std::string(message) + " failed with XrResult: " + std::to_string(result));
    }
}
}

Controllers::Controllers(XrInstance instance, XrSession session, XrSpace reference_space)
    : session_(session), reference_space_(reference_space)
{
    try
    {
        create_actions(instance);
        setup_action_spaces(session);
    }
    catch (...)
    {
        cleanup();
        throw;
    }
}

Controllers::~Controllers()
{
    cleanup();
}

void Controllers::create_actions(XrInstance instance)
{
    // Create action set
    XrActionSetCreateInfo action_set_info{ XR_TYPE_ACTION_SET_CREATE_INFO };
    strcpy(action_set_info.actionSetName, "controller_actions");
    strcpy(action_set_info.localizedActionSetName, "Controller Actions");
    action_set_info.priority = 0;

    CheckXrResult(xrCreateActionSet(instance, &action_set_info, &action_set_), "xrCreateActionSet");

    // Create paths
    CheckXrResult(xrStringToPath(instance, "/user/hand/left", &left_hand_path_), "xrStringToPath(left)");
    CheckXrResult(xrStringToPath(instance, "/user/hand/right", &right_hand_path_), "xrStringToPath(right)");

    XrPath hand_paths[2] = { left_hand_path_, right_hand_path_ };

    // Create grip pose action
    XrActionCreateInfo grip_action_info{ XR_TYPE_ACTION_CREATE_INFO };
    grip_action_info.actionType = XR_ACTION_TYPE_POSE_INPUT;
    strcpy(grip_action_info.actionName, "grip_pose");
    strcpy(grip_action_info.localizedActionName, "Grip Pose");
    grip_action_info.countSubactionPaths = 2;
    grip_action_info.subactionPaths = hand_paths;

    CheckXrResult(xrCreateAction(action_set_, &grip_action_info, &grip_pose_action_), "xrCreateAction(grip_pose)");

    // Create aim pose action
    XrActionCreateInfo aim_action_info{ XR_TYPE_ACTION_CREATE_INFO };
    aim_action_info.actionType = XR_ACTION_TYPE_POSE_INPUT;
    strcpy(aim_action_info.actionName, "aim_pose");
    strcpy(aim_action_info.localizedActionName, "Aim Pose");
    aim_action_info.countSubactionPaths = 2;
    aim_action_info.subactionPaths = hand_paths;

    CheckXrResult(xrCreateAction(action_set_, &aim_action_info, &aim_pose_action_), "xrCreateAction(aim_pose)");

    // Create trigger action (boolean for simple_controller select/click)
    XrActionCreateInfo trigger_action_info{ XR_TYPE_ACTION_CREATE_INFO };
    trigger_action_info.actionType = XR_ACTION_TYPE_BOOLEAN_INPUT;
    strcpy(trigger_action_info.actionName, "trigger");
    strcpy(trigger_action_info.localizedActionName, "Trigger");
    trigger_action_info.countSubactionPaths = 2;
    trigger_action_info.subactionPaths = hand_paths;

    CheckXrResult(xrCreateAction(action_set_, &trigger_action_info, &trigger_action_), "xrCreateAction(trigger)");

    // Suggest bindings for simple_controller profile
    XrPath interaction_profile_path;
    CheckXrResult(xrStringToPath(instance, "/interaction_profiles/khr/simple_controller", &interaction_profile_path),
                  "xrStringToPath(profile)");

    std::vector<XrActionSuggestedBinding> bindings;
    XrPath left_grip_path, right_grip_path, left_aim_path, right_aim_path;
    XrPath left_trigger_path, right_trigger_path;

    CheckXrResult(xrStringToPath(instance, "/user/hand/left/input/grip/pose", &left_grip_path), "xrStringToPath");
    CheckXrResult(xrStringToPath(instance, "/user/hand/right/input/grip/pose", &right_grip_path), "xrStringToPath");
    CheckXrResult(xrStringToPath(instance, "/user/hand/left/input/aim/pose", &left_aim_path), "xrStringToPath");
    CheckXrResult(xrStringToPath(instance, "/user/hand/right/input/aim/pose", &right_aim_path), "xrStringToPath");
    CheckXrResult(xrStringToPath(instance, "/user/hand/left/input/select/click", &left_trigger_path), "xrStringToPath");
    CheckXrResult(xrStringToPath(instance, "/user/hand/right/input/select/click", &right_trigger_path), "xrStringToPath");

    bindings.push_back({ grip_pose_action_, left_grip_path });
    bindings.push_back({ grip_pose_action_, right_grip_path });
    bindings.push_back({ aim_pose_action_, left_aim_path });
    bindings.push_back({ aim_pose_action_, right_aim_path });
    bindings.push_back({ trigger_action_, left_trigger_path });
    bindings.push_back({ trigger_action_, right_trigger_path });

    XrInteractionProfileSuggestedBinding suggested_bindings{ XR_TYPE_INTERACTION_PROFILE_SUGGESTED_BINDING };
    suggested_bindings.interactionProfile = interaction_profile_path;
    suggested_bindings.countSuggestedBindings = static_cast<uint32_t>(bindings.size());
    suggested_bindings.suggestedBindings = bindings.data();

    CheckXrResult(
        xrSuggestInteractionProfileBindings(instance, &suggested_bindings), "xrSuggestInteractionProfileBindings");

    // Attach action set to session
    XrSessionActionSetsAttachInfo attach_info{ XR_TYPE_SESSION_ACTION_SETS_ATTACH_INFO };
    attach_info.countActionSets = 1;
    attach_info.actionSets = &action_set_;

    CheckXrResult(xrAttachSessionActionSets(session_, &attach_info), "xrAttachSessionActionSets");
}

void Controllers::setup_action_spaces(XrSession session)
{
    XrActionSpaceCreateInfo space_info{ XR_TYPE_ACTION_SPACE_CREATE_INFO };
    space_info.action = grip_pose_action_;
    space_info.poseInActionSpace.orientation = { 0.0f, 0.0f, 0.0f, 1.0f };
    space_info.poseInActionSpace.position = { 0.0f, 0.0f, 0.0f };

    // Create grip spaces
    space_info.subactionPath = left_hand_path_;
    CheckXrResult(xrCreateActionSpace(session, &space_info, &left_grip_space_), "xrCreateActionSpace(left_grip)");

    space_info.subactionPath = right_hand_path_;
    CheckXrResult(xrCreateActionSpace(session, &space_info, &right_grip_space_), "xrCreateActionSpace(right_grip)");

    // Create aim spaces
    space_info.action = aim_pose_action_;
    space_info.subactionPath = left_hand_path_;
    CheckXrResult(xrCreateActionSpace(session, &space_info, &left_aim_space_), "xrCreateActionSpace(left_aim)");

    space_info.subactionPath = right_hand_path_;
    CheckXrResult(xrCreateActionSpace(session, &space_info, &right_aim_space_), "xrCreateActionSpace(right_aim)");
}

void Controllers::update(XrTime time)
{
    // Sync actions
    XrActionsSyncInfo sync_info{ XR_TYPE_ACTIONS_SYNC_INFO };
    XrActiveActionSet active_action_set{ action_set_, XR_NULL_PATH };
    sync_info.countActiveActionSets = 1;
    sync_info.activeActionSets = &active_action_set;

    CheckXrResult(xrSyncActions(session_, &sync_info), "xrSyncActions");

    // Get poses
    locate_pose(left_grip_space_, time, left_.grip_pose, left_.grip_valid);
    locate_pose(left_aim_space_, time, left_.aim_pose, left_.aim_valid);
    locate_pose(right_grip_space_, time, right_.grip_pose, right_.grip_valid);
    locate_pose(right_aim_space_, time, right_.aim_pose, right_.aim_valid);

    // Get trigger values (boolean for simple_controller select/click)
    XrActionStateBoolean trigger_state{ XR_TYPE_ACTION_STATE_BOOLEAN };
    XrActionStateGetInfo get_info{ XR_TYPE_ACTION_STATE_GET_INFO };
    get_info.action = trigger_action_;

    // Left hand
    get_info.subactionPath = left_hand_path_;
    if (XR_SUCCEEDED(xrGetActionStateBoolean(session_, &get_info, &trigger_state)) && trigger_state.isActive)
    {
        left_.trigger_value = trigger_state.currentState ? 1.0f : 0.0f;
    }
    else
    {
        left_.trigger_value = 0.0f;
    }

    // Right hand
    get_info.subactionPath = right_hand_path_;
    if (XR_SUCCEEDED(xrGetActionStateBoolean(session_, &get_info, &trigger_state)) && trigger_state.isActive)
    {
        right_.trigger_value = trigger_state.currentState ? 1.0f : 0.0f;
    }
    else
    {
        right_.trigger_value = 0.0f;
    }
}

void Controllers::locate_pose(XrSpace space, XrTime time, XrPosef& pose, bool& is_valid)
{
    XrSpaceLocation location{ XR_TYPE_SPACE_LOCATION };
    // For pose location, we don't necessarily want to throw if it fails, just mark invalid
    // unless it's a catastrophic error? But XR_FAILED usually means invalid handle or session lost.
    if (XR_FAILED(xrLocateSpace(space, reference_space_, time, &location)))
    {
        is_valid = false;
        return;
    }

    is_valid = (location.locationFlags & XR_SPACE_LOCATION_POSITION_VALID_BIT) &&
               (location.locationFlags & XR_SPACE_LOCATION_ORIENTATION_VALID_BIT);
    pose = location.pose;
}

void Controllers::cleanup()
{
    if (left_grip_space_ != XR_NULL_HANDLE)
    {
        xrDestroySpace(left_grip_space_);
        left_grip_space_ = XR_NULL_HANDLE;
    }
    if (right_grip_space_ != XR_NULL_HANDLE)
    {
        xrDestroySpace(right_grip_space_);
        right_grip_space_ = XR_NULL_HANDLE;
    }
    if (left_aim_space_ != XR_NULL_HANDLE)
    {
        xrDestroySpace(left_aim_space_);
        left_aim_space_ = XR_NULL_HANDLE;
    }
    if (right_aim_space_ != XR_NULL_HANDLE)
    {
        xrDestroySpace(right_aim_space_);
        right_aim_space_ = XR_NULL_HANDLE;
    }
    if (action_set_ != XR_NULL_HANDLE)
    {
        xrDestroyActionSet(action_set_);
        action_set_ = XR_NULL_HANDLE;
    }
}

} // namespace plugin_utils
