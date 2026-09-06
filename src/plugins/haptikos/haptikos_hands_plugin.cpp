// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "haptikos_hands_plugin.hpp"

#include <oxr_utils/os_time.hpp>
#include <oxr_utils/pose_conversions.hpp>

#include <chrono>
#include <cstdlib>
#include <iostream>
#include <stdexcept>
#include <utility>

namespace plugins
{
namespace haptikos
{

HaptikosHandsPlugin::HaptikosHandsPlugin(const std::string& plugin_root_id,
                                         std::shared_ptr<core::ControllerTracker> controller_tracker,
                                         core::PluginSessionHandle plugin_session) noexcept(false)
    : m_controller_tracker(std::move(controller_tracker)),
      m_plugin_session(std::move(plugin_session)),
      m_root_id(plugin_root_id)
{
    static_assert(XR_HAND_JOINT_COUNT_EXT == HAPTIKOS_NUM_OF_JOINTS, "Unexpected XR Hand Joint number");
    std::cout << "Initializing HaptikosHandsPlugin with root: " << m_root_id << std::endl;

    if (!m_controller_tracker || !m_plugin_session)
    {
        throw std::invalid_argument("HaptikosHandsPlugin requires a controller tracker and plugin session");
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
    m_thread = std::thread(&HaptikosHandsPlugin::worker_thread, this);

    std::cout << "HaptikosHandsPlugin initialized and running" << std::endl;
}


HaptikosHandsPlugin::~HaptikosHandsPlugin()
{
    std::cout << "Shutting down HaptikosHandsPlugin..." << std::endl;

    m_running = false;
    m_thread.join();
}

void HaptikosHandsPlugin::worker_thread()
{
    XrHandJointLocationEXT left_joints[XR_HAND_JOINT_COUNT_EXT];
    XrHandJointLocationEXT right_joints[XR_HAND_JOINT_COUNT_EXT];

    const auto target_frame_duration = std::chrono::nanoseconds(1000000000 / 90);

    while (m_running)
    {
        auto frame_start = std::chrono::steady_clock::now();

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
            std::cerr << "HaptikosHandsPlugin update error: " << e.what() << std::endl;
            m_left_pusher.reset();
            m_right_pusher.reset();
            std::exit(1);
        }
        catch (...)
        {
            std::cerr << "HaptikosHandsPlugin update error: unknown exception" << std::endl;
            m_left_pusher.reset();
            m_right_pusher.reset();
            std::exit(1);
        }

        const int64_t sample_time_ns = core::os_monotonic_now_ns();


        bool rigth_published = false;
        if (right_tracked)
        {
            Haptikos::HandData right_data = m_client.GetData(true, Haptikos::GlobalToWrist, true, true, false);
            bool valid_wrist = false;
            XrPosef rigth_controller = oxr_utils::get_aim_pose(*right_tracked, valid_wrist);

            if (right_data.IsValid() == 1 && valid_wrist)
            {
                calculate_hand_pose(right_joints, right_data, rigth_controller);
                if (!m_right_pusher)
                {
                    m_right_pusher = std::make_unique<core::HandTrackingPusher>(
                        m_plugin_session->create_hand_tracking_push_channel(XR_HAND_RIGHT_EXT));
                }

                m_right_pusher->push(right_joints, sample_time_ns);
                rigth_published = true;
            }
        }


        if (!rigth_published && m_right_pusher)
        {
            m_right_pusher.reset();
        }


        bool left_published = false;
        if (left_tracked)
        {
            Haptikos::HandData left_data = m_client.GetData(false, Haptikos::GlobalToWrist, true, true, false);
            bool valid_wrist = false;
            XrPosef left_controller = oxr_utils::get_aim_pose(*left_tracked, valid_wrist);

            if (left_data.IsValid() == 1 && valid_wrist)
            {
                calculate_hand_pose(left_joints, left_data, left_controller);

                if (!m_left_pusher)
                {
                    m_left_pusher = std::make_unique<core::HandTrackingPusher>(
                        m_plugin_session->create_hand_tracking_push_channel(XR_HAND_LEFT_EXT));
                }
                m_left_pusher->push(left_joints, sample_time_ns);
                left_published = true;
            }
        }

        if (!left_published && m_left_pusher)
        {
            m_left_pusher.reset();
        }

        std::this_thread::sleep_until(frame_start + target_frame_duration);
    }
}

void HaptikosHandsPlugin::calculate_hand_pose(XrHandJointLocationEXT* result,
                                              const Haptikos::HandData& data,
                                              const XrPosef& controller_pose)
{
    Haptikos::Vector3 wrist_offest = Haptikos::Vector3(0, -0.05f, -0.06f);
    Haptikos::Quaternion wrist_rotation;
    data.GetHandRotation(wrist_rotation);

    wrist_offest = wrist_rotation.RotateVector(wrist_offest);

    Haptikos::Vector3 wrist_pos =
        Haptikos::Vector3(controller_pose.position.x, -controller_pose.position.z, controller_pose.position.y) +
        wrist_offest;
    std::array<Haptikos::Vector3, HAPTIKOS_NUM_OF_JOINTS> positions;
    std::array<Haptikos::Quaternion, HAPTIKOS_NUM_OF_JOINTS> rotations;

    data.GetPositions(positions);
    data.GetRotations(rotations);

    for (int i = 0; i < XR_HAND_JOINT_COUNT_EXT; i++)
    {
        Haptikos::Vector3 pos = positions[i] + wrist_pos;
        Haptikos::Quaternion rot = rotations[i];

        result[i].pose = get_pose(pos, rot);
        result[i].locationFlags = XR_SPACE_LOCATION_POSITION_VALID_BIT | XR_SPACE_LOCATION_ORIENTATION_VALID_BIT |
                                  XR_SPACE_LOCATION_POSITION_TRACKED_BIT | XR_SPACE_LOCATION_ORIENTATION_TRACKED_BIT;
    }
}

XrPosef HaptikosHandsPlugin::get_pose(const Haptikos::Vector3& position, const Haptikos::Quaternion& rotation)
{
    XrPosef result;
    result.position.x = position.x;
    result.position.y = position.z;
    result.position.z = -position.y;

    result.orientation.x = rotation.x;
    result.orientation.y = rotation.z;
    result.orientation.z = -rotation.y;
    result.orientation.w = rotation.w;

    return result;
}

} // namespace haptikos
} // namespace plugins
