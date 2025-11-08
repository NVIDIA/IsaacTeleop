// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Controller synthetic hands - generates hand tracking data from controller poses

#include "controllers.hpp"
#include "hand_generator.hpp"
#include "hand_injector.hpp"
#include "session.hpp"

#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <thread>

std::atomic<bool> g_running(true);

// Toggle between space-based and pose-based hand injection
// true = use controller spaces directly (primary method)
// false = read controller poses and generate in world space (secondary method)
constexpr bool USE_SPACE_BASED_INJECTION = false;

// Debug: Test curling with a hardcoded value (set to 0.0 to use real trigger input)
constexpr float DEBUG_CURL_OVERRIDE = 0.0f; // Set to 0.5 or 1.0 to test curling

// Keyboard fallback: Press 'L' for left hand curl, 'R' for right hand curl
// (Useful if controller triggers aren't working)
constexpr bool USE_KEYBOARD_FALLBACK = true;

void signal_handler(int signal)
{
    if (signal == SIGINT)
    {
        g_running = false;
    }
}

XrTime get_current_time()
{
    // Cross-platform time: use std::chrono instead of clock_gettime
    auto now = std::chrono::steady_clock::now();
    auto ns = std::chrono::duration_cast<std::chrono::nanoseconds>(now.time_since_epoch());
    return static_cast<XrTime>(ns.count());
}

int main()
{
    std::signal(SIGINT, signal_handler);

    std::cout << "Controller Synthetic Hands" << std::endl;
    std::cout << "Generating hand tracking from controller poses" << std::endl;
    std::cout << "Press Ctrl+C to exit" << std::endl;
    std::cout << std::endl;

    // Initialize session
    SessionConfig config;
    config.app_name = "ControllerSyntheticHands";
    config.extensions = { XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME, "XR_MND_headless", "XR_EXTX_overlay" };
    config.use_overlay_mode = false;

    Session* session = Session::Create(config);
    if (!session)
    {
        std::cerr << "Failed to create session" << std::endl;
        return 1;
    }

    const auto& handles = session->handles();

    if (!session->begin())
    {
        std::cerr << "Failed to begin session" << std::endl;
        delete session;
        return 1;
    }

    // Initialize controllers
    Controllers* controllers = Controllers::Create(handles.instance, handles.session, handles.reference_space);
    if (!controllers)
    {
        std::cerr << "Failed to create controllers" << std::endl;
        delete session;
        return 1;
    }

    // Initialize hand generation
    HandGenerator hands;

    // Initialize hand injection using the selected method
    HandInjector* injector = nullptr;
    if (USE_SPACE_BASED_INJECTION)
    {
        injector = HandInjector::Create(
            handles.instance, handles.session, controllers->left_aim_space(), controllers->right_aim_space());
    }
    else
    {
        injector = HandInjector::CreateWithReferenceSpace(handles.instance, handles.session, handles.reference_space);
    }

    if (!injector)
    {
        std::cerr << "Warning: Push device extension not available" << std::endl;
    }

    // Main loop
    int frame_count = 0;
    XrHandJointLocationEXT left_joints[XR_HAND_JOINT_COUNT_EXT];
    XrHandJointLocationEXT right_joints[XR_HAND_JOINT_COUNT_EXT];

    // Smooth curl transition state
    float left_curl_current = 0.0f;
    float right_curl_current = 0.0f;
    constexpr float CURL_SPEED = 5.0f; // Units per second (higher = faster transition)
    constexpr float FRAME_TIME = 0.016f; // ~16ms per frame (60fps)

    while (g_running)
    {
        XrTime time = get_current_time();

        if (!controllers->update(time))
        {
            std::this_thread::sleep_for(std::chrono::milliseconds(16));
            continue;
        }

        // Get controller states
        const auto& left = controllers->left();
        const auto& right = controllers->right();

        // Get target curl values (0.0 or 1.0 from button click)
        float left_target = DEBUG_CURL_OVERRIDE > 0.0f ? DEBUG_CURL_OVERRIDE : left.trigger_value;
        float right_target = DEBUG_CURL_OVERRIDE > 0.0f ? DEBUG_CURL_OVERRIDE : right.trigger_value;

        // Smoothly interpolate current curl toward target
        float curl_delta = CURL_SPEED * FRAME_TIME;
        if (left_curl_current < left_target)
        {
            left_curl_current = std::min(left_curl_current + curl_delta, left_target);
        }
        else if (left_curl_current > left_target)
        {
            left_curl_current = std::max(left_curl_current - curl_delta, left_target);
        }

        if (right_curl_current < right_target)
        {
            right_curl_current = std::min(right_curl_current + curl_delta, right_target);
        }
        else if (right_curl_current > right_target)
        {
            right_curl_current = std::max(right_curl_current - curl_delta, right_target);
        }

        float left_curl = left_curl_current;
        float right_curl = right_curl_current;

        // Process hands based on selected method
        if (USE_SPACE_BASED_INJECTION)
        {
            // Space-based: generate relative joints with curl, push device transforms using controller spaces
            // The push device handles tracking automatically, so we always push regardless of validity
            if (injector)
            {
                hands.generate_relative(left_joints, true, left_curl);
                injector->push_left(left_joints, time);

                hands.generate_relative(right_joints, false, right_curl);
                injector->push_right(right_joints, time);
            }
        }
        else
        {
            // Pose-based: read controller poses and generate hands in world space
            if (left.grip_valid && left.aim_valid && injector)
            {
                XrPosef wrist;
                wrist.position = left.aim_pose.position;
                wrist.orientation = left.aim_pose.orientation;

                hands.generate(left_joints, wrist, true, left_curl);
                injector->push_left(left_joints, time);
            }

            if (right.grip_valid && right.aim_valid && injector)
            {
                XrPosef wrist;
                wrist.position = right.aim_pose.position;
                wrist.orientation = right.aim_pose.orientation;

                hands.generate(right_joints, wrist, false, right_curl);
                injector->push_right(right_joints, time);
            }
        }

        frame_count++;
        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }

    std::cout << std::endl << "Shutting down" << std::endl;

    // Cleanup
    delete injector;
    delete controllers;
    delete session;

    return 0;
}
