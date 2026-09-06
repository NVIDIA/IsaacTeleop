// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "synthetic_hands_plugin.hpp"

#include <oxr_utils/os_time.hpp>
#include <oxr_utils/pose_conversions.hpp>

#include <algorithm>
#include <chrono>
#include <cstdlib>
#include <exception>
#include <iostream>
#include <stdexcept>
#include <utility>

namespace plugins
{
namespace controller_synthetic_hands
{

SyntheticHandsPlugin::SyntheticHandsPlugin(const std::string& plugin_root_id,
                                           std::shared_ptr<core::ControllerTracker> controller_tracker,
                                           core::PluginSessionHandle plugin_session) noexcept(false)
    : m_controller_tracker(std::move(controller_tracker)),
      m_plugin_session(std::move(plugin_session)),
      m_root_id(plugin_root_id)
{
    std::cout << "Initializing SyntheticHandsPlugin with root: " << m_root_id << std::endl;

    if (!m_controller_tracker || !m_plugin_session)
    {
        throw std::invalid_argument("SyntheticHandsPlugin requires a controller tracker and plugin session");
    }
    m_pull_channel = m_plugin_session->create_pull_channel();
    if (!m_pull_channel)
    {
        throw std::runtime_error("The plugin session could not create a pull channel");
    }

    // Pushers are created lazily in worker_thread once a controller is first seen,
    // and destroyed when the controller disappears. This ensures isActive reflects
    // whether a controller is actually present.

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
        core::Serialized<core::ControllerSnapshot> left_tracked;
        core::Serialized<core::ControllerSnapshot> right_tracked;
        try
        {
            m_pull_channel->update();

            // Read tracker data in the same exception boundary as update.
            left_tracked = m_controller_tracker->get_left_controller(*m_pull_channel);
            right_tracked = m_controller_tracker->get_right_controller(*m_pull_channel);
        }
        catch (const std::exception& e)
        {
            std::cerr << "SyntheticHandsPlugin update error: " << e.what() << std::endl;
            m_left_pusher.reset();
            m_right_pusher.reset();
            std::exit(1);
        }
        catch (...)
        {
            std::cerr << "SyntheticHandsPlugin update error: unknown exception" << std::endl;
            m_left_pusher.reset();
            m_right_pusher.reset();
            std::exit(1);
        }

        const int64_t sample_time_ns = core::os_monotonic_now_ns();

        // Get target curl values from trigger inputs
        float left_target = 0.0f;
        float right_target = 0.0f;

        if (left_tracked)
            left_target = left_tracked->inputs()->trigger_value();
        if (right_tracked)
            right_target = right_tracked->inputs()->trigger_value();

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
        // pusher. A different plugin could choose a different policy — for example, a
        // plugin with independent joint data (e.g. a glove) could keep pushing joints
        // even when no controller pose is available.
        if (m_left_enabled && left_tracked)
        {
            bool grip_valid = false;
            bool aim_valid = false;
            oxr_utils::get_grip_pose(*left_tracked, grip_valid);
            XrPosef wrist = oxr_utils::get_aim_pose(*left_tracked, aim_valid);

            if (grip_valid && aim_valid)
            {
                if (!m_left_pusher)
                {
                    m_left_pusher = std::make_unique<core::HandTrackingPusher>(
                        m_plugin_session->create_hand_tracking_push_channel(XR_HAND_LEFT_EXT));
                }
                m_hand_gen.generate(left_joints, wrist, true, left_curl_current);
                m_left_pusher->push(left_joints, sample_time_ns);
            }
        }
        else
        {
            // Controller not present — destroy the pusher so the receiver sees
            // isActive=false rather than a frozen hand pose.
            m_left_pusher.reset();
        }

        if (m_right_enabled && right_tracked)
        {
            bool grip_valid = false;
            bool aim_valid = false;
            oxr_utils::get_grip_pose(*right_tracked, grip_valid);
            XrPosef wrist = oxr_utils::get_aim_pose(*right_tracked, aim_valid);

            if (grip_valid && aim_valid)
            {
                if (!m_right_pusher)
                {
                    m_right_pusher = std::make_unique<core::HandTrackingPusher>(
                        m_plugin_session->create_hand_tracking_push_channel(XR_HAND_RIGHT_EXT));
                }
                m_hand_gen.generate(right_joints, wrist, false, right_curl_current);
                m_right_pusher->push(right_joints, sample_time_ns);
            }
        }
        else
        {
            // Controller not present — destroy the pusher so the receiver sees
            // isActive=false rather than a frozen hand pose.
            m_right_pusher.reset();
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }
}

} // namespace controller_synthetic_hands
} // namespace plugins
