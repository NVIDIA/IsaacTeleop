// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <controller_synthetic_hands/synthetic_hands_plugin.hpp>
#include <oxr_utils/pose_conversions.hpp>

#include <algorithm>
#include <chrono>
#include <iostream>

namespace plugins
{
namespace controller_synthetic_hands
{

SyntheticHandsPlugin::SyntheticHandsPlugin(const std::string& plugin_root_id) noexcept(false)
    : m_root_id(plugin_root_id)
{
    std::cout << "Initializing SyntheticHandsPlugin with root: " << m_root_id << std::endl;

    // Create ControllerTracker first to get required extensions
    m_controller_tracker = std::make_shared<core::ControllerTracker>();
    std::vector<std::shared_ptr<core::ITracker>> trackers = { m_controller_tracker };

    // Get required extensions from trackers
    auto extensions = core::DeviceIOSession::get_required_extensions(trackers);
    extensions.push_back(XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME);

    // Initialize session - constructor automatically begins the session
    m_session = std::make_shared<core::OpenXRSession>("ControllerSyntheticHands", extensions);
    const auto handles = m_session->get_handles();

    // Create DeviceIOSession with trackers
    m_deviceio_session = core::DeviceIOSession::run(trackers, handles);

    // Injectors are created lazily in worker_thread once a controller is first seen,
    // and destroyed when the controller disappears. This ensures isActive reflects
    // whether a controller is actually present.
    m_time_converter.emplace(handles);

    // Start worker thread
    m_running = true;
    m_thread = std::thread(&SyntheticHandsPlugin::worker_thread, this);

    std::cout << "SyntheticHandsPlugin initialized and running" << std::endl;
}

SyntheticHandsPlugin::~SyntheticHandsPlugin()
{
    std::cout << "Shutting down SyntheticHandsPlugin..." << std::endl;

    m_running = false;
    m_thread.join();
}

void SyntheticHandsPlugin::worker_thread()
{
    XrHandJointLocationEXT left_joints[XR_HAND_JOINT_COUNT_EXT];
    XrHandJointLocationEXT right_joints[XR_HAND_JOINT_COUNT_EXT];

    // Smooth curl transition state
    float left_curl_current = 0.0f;
    float right_curl_current = 0.0f;
    constexpr float CURL_SPEED = 5.0f;
    constexpr float FRAME_TIME = 0.016f;

    while (m_running)
    {
        // Update DeviceIOSession (handles time and tracker updates)
        if (!m_deviceio_session->update())
        {
            std::cerr << "DeviceIOSession update failed" << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(16));
            continue;
        }

        // Get controller data from tracker
        const auto& left_tracked = m_controller_tracker->get_left_controller(*m_deviceio_session);
        const auto& right_tracked = m_controller_tracker->get_right_controller(*m_deviceio_session);

        // Use the OpenXR runtime clock for injection time so it aligns with the
        // runtime's own time domain (XrTime), rather than a raw steady_clock cast.
        XrTime time = m_time_converter->os_monotonic_now();

        // Get target curl values from trigger inputs
        float left_target = 0.0f;
        float right_target = 0.0f;

        if (left_tracked.data)
            left_target = left_tracked.data->inputs->trigger_value();
        if (right_tracked.data)
            right_target = right_tracked.data->inputs->trigger_value();

        // Smoothly interpolate
        float curl_delta = CURL_SPEED * FRAME_TIME;

        if (left_curl_current < left_target)
            left_curl_current = std::min(left_curl_current + curl_delta, left_target);
        else if (left_curl_current > left_target)
            left_curl_current = std::max(left_curl_current - curl_delta, left_target);

        if (right_curl_current < right_target)
            right_curl_current = std::min(right_curl_current + curl_delta, right_target);
        else if (right_curl_current > right_target)
            right_curl_current = std::max(right_curl_current - curl_delta, right_target);

        // Update exposed state
        {
            std::lock_guard<std::mutex> lock(m_state_mutex);
            m_left_curl = left_curl_current;
            m_right_curl = right_curl_current;
        }

        // This plugin treats controller presence as a prerequisite for hand injection:
        // if the controller is gone, the synthetic hand is deactivated by resetting the
        // injector. A different plugin could choose a different policy — for example, a
        // plugin with independent joint data (e.g. a glove) could keep pushing joints
        // even when no controller pose is available.
        if (m_left_enabled && left_tracked.data)
        {
            bool grip_valid = false;
            bool aim_valid = false;
            oxr_utils::get_grip_pose(*left_tracked.data, grip_valid);
            XrPosef wrist = oxr_utils::get_aim_pose(*left_tracked.data, aim_valid);

            if (grip_valid && aim_valid)
            {
                if (!m_left_injector)
                {
                    const auto handles = m_session->get_handles();
                    m_left_injector = std::make_unique<plugin_utils::HandInjector>(
                        handles.instance, handles.session, XR_HAND_LEFT_EXT, handles.space);
                }
                m_hand_gen.generate(left_joints, wrist, true, left_curl_current);
                m_left_injector->push(left_joints, time);
            }
        }
        else
        {
            // Controller not present — destroy the injector so the runtime sees
            // isActive=false rather than a frozen hand pose.
            m_left_injector.reset();
        }

        if (m_right_enabled && right_tracked.data)
        {
            bool grip_valid = false;
            bool aim_valid = false;
            oxr_utils::get_grip_pose(*right_tracked.data, grip_valid);
            XrPosef wrist = oxr_utils::get_aim_pose(*right_tracked.data, aim_valid);

            if (grip_valid && aim_valid)
            {
                if (!m_right_injector)
                {
                    const auto handles = m_session->get_handles();
                    m_right_injector = std::make_unique<plugin_utils::HandInjector>(
                        handles.instance, handles.session, XR_HAND_RIGHT_EXT, handles.space);
                }
                m_hand_gen.generate(right_joints, wrist, false, right_curl_current);
                m_right_injector->push(right_joints, time);
            }
        }
        else
        {
            // Controller not present — destroy the injector so the runtime sees
            // isActive=false rather than a frozen hand pose.
            m_right_injector.reset();
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }
}

} // namespace controller_synthetic_hands
} // namespace plugins
