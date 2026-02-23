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

    // Initialize hand injection (world space mode only - space-based injection would need
    // access to controller spaces which are internal to ControllerTracker)
    m_injector.emplace(handles.instance, handles.session, handles.space);

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
        const auto& left_ctrl = m_controller_tracker->get_left_controller(*m_deviceio_session);
        const auto& right_ctrl = m_controller_tracker->get_right_controller(*m_deviceio_session);

        // Get timestamp from controller data
        XrTime time = 0;
        if (left_ctrl.is_active())
        {
            time = left_ctrl.timestamp().device_time();
        }
        else if (right_ctrl.is_active())
        {
            time = right_ctrl.timestamp().device_time();
        }

        // Get target curl values from trigger inputs
        float left_target = 0.0f;
        float right_target = 0.0f;

        left_target = left_ctrl.inputs().trigger_value();
        right_target = right_ctrl.inputs().trigger_value();

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

        if (m_left_enabled && left_ctrl.is_active())
        {
            bool grip_valid = false;
            bool aim_valid = false;
            oxr_utils::get_grip_pose(left_ctrl, grip_valid);
            XrPosef wrist = oxr_utils::get_aim_pose(left_ctrl, aim_valid);

            if (grip_valid && aim_valid)
            {
                m_hand_gen.generate(left_joints, wrist, true, left_curl_current);
                m_injector->push_left(left_joints, time);
            }
        }

        if (m_right_enabled && right_ctrl.is_active())
        {
            bool grip_valid = false;
            bool aim_valid = false;
            oxr_utils::get_grip_pose(right_ctrl, grip_valid);
            XrPosef wrist = oxr_utils::get_aim_pose(right_ctrl, aim_valid);

            if (grip_valid && aim_valid)
            {
                m_hand_gen.generate(right_joints, wrist, false, right_curl_current);
                m_injector->push_right(right_joints, time);
            }
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }
}

} // namespace controller_synthetic_hands
} // namespace plugins
