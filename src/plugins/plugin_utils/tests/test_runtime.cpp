// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <catch2/catch_test_macros.hpp>
#include <plugin_utils/controllers.hpp>
#include <plugin_utils/hand_injector.hpp>
#include <plugin_utils/session.hpp>

#include <iostream>
#include <string>
#include <vector>

TEST_CASE("Session Initialization", "[session]")
{
    plugin_utils::SessionConfig config;
    config.app_name = "TestApp";

    // This calls xrCreateInstance, xrGetSystem, xrCreateSession, xrCreateReferenceSpace
    plugin_utils::Session session(config);

    REQUIRE(session.handles().instance != XR_NULL_HANDLE);
    REQUIRE(session.handles().session != XR_NULL_HANDLE);
    REQUIRE(session.handles().reference_space != XR_NULL_HANDLE);

    session.begin(); // calls xrBeginSession
    // Session destructor calls cleanup -> xrDestroySession, xrDestroyInstance
}

TEST_CASE("Controllers Logic", "[controllers]")
{
    XrInstance instance = (XrInstance)0x1;
    XrSession session = (XrSession)0x2;
    XrSpace space = (XrSpace)0x3;

    // Calls xrCreateActionSet, xrStringToPath, xrCreateAction, etc.
    plugin_utils::Controllers controllers(instance, session, space);

    // Test update (calls xrSyncActions, xrLocateSpace, xrGetActionStateBoolean)
    controllers.update(0);

    const auto& left = controllers.left();
    // In mock, locate returns valid, so flags should be valid
    REQUIRE(left.grip_valid);
    REQUIRE(left.aim_valid);

    // Trigger is inactive by default in mock?
    // mock_xrGetActionStateBoolean sets isActive=TRUE, currentState=FALSE.
    // So trigger value should be 0.0f.
    REQUIRE(left.trigger_value == 0.0f);
}

TEST_CASE("HandInjector Logic", "[hand_injector]")
{
    XrInstance instance = (XrInstance)0x1;
    XrSession session = (XrSession)0x2;
    XrSpace space = (XrSpace)0x3;

    // Calls xrGetInstanceProcAddr, xrCreatePushDeviceNV
    plugin_utils::HandInjector injector(instance, session, space);

    // Calls xrPushDevicePushHandTrackingNV
    XrHandJointLocationEXT joints[XR_HAND_JOINT_COUNT_EXT] = {};
    // Initialize dummy joints
    for (int i = 0; i < XR_HAND_JOINT_COUNT_EXT; ++i)
    {
        joints[i].pose.orientation.w = 1.0f;
    }

    injector.push_left(joints, 0);
    injector.push_right(joints, 0);

    // If we got here without throwing, it's a pass.
    SUCCEED("HandInjector push succeeded");
}
