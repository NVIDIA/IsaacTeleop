// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <haptikos/haptikos_hands_plugin.hpp>
#include <oxr_utils/pose_conversions.hpp>

#include <chrono>

namespace plugins
{
namespace haptikos
{

HaptikosHandsPlugin::HaptikosHandsPlugin(const std::string& plugin_root_id) noexcept(false) : m_root_id(plugin_root_id)
{
    static_assert(XR_HAND_JOINT_COUNT_EXT == HAPTIKOS_NUM_OF_JOINTS, "Unexpected XR Hand Joint number");
    std::cout << "Initializing HaptikosHandsPlugin with root: " << m_root_id << std::endl;

    // Create ControllerTracker first to get required extensions
    m_controller_tracker = std::make_shared<core::ControllerTracker>();
    m_hand_tracker = std::make_shared<core::HandTracker>();
    std::vector<std::shared_ptr<core::ITracker>> trackers = { m_controller_tracker, m_hand_tracker };

    // Get required extensions from trackers
    auto extensions = core::DeviceIOSession::get_required_extensions(trackers);
    extensions.push_back(XR_NVX1_DEVICE_INTERFACE_BASE_EXTENSION_NAME);

    // Initialize session - constructor automatically begins the session
    m_session = std::make_shared<core::OpenXRSession>("HaptikosHands", extensions);
    const auto handles = m_session->get_handles();

    // Create DeviceIOSession with trackers
    m_deviceio_session = core::DeviceIOSession::run(trackers, handles);

    // Injectors are created lazily in worker_thread once a controller is first seen,
    // and destroyed when the controller disappears. This ensures isActive reflects
    // whether a controller is actually present.
    m_time_converter.emplace(handles);

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

        core::ControllerSnapshotTrackedT left_tracked;
        core::ControllerSnapshotTrackedT right_tracked;

        core::HandPoseTrackedT left_hand;
        core::HandPoseTrackedT rigth_hand;

        try
        {
            // Update DeviceIOSession (handles time and tracker updates)
            m_deviceio_session->update();

            // Read tracker data in the same exception boundary as update.
            left_tracked = m_controller_tracker->get_left_controller(*m_deviceio_session);
            right_tracked = m_controller_tracker->get_right_controller(*m_deviceio_session);
        }
        catch (const std::exception& e)
        {
            std::cerr << "HaptikosHandsPlugin update error: " << e.what() << std::endl;
            m_left_injector.reset();
            m_right_injector.reset();
            std::exit(1);
        }
        catch (...)
        {
            std::cerr << "HaptikosHandsPlugin update error: unknown exception" << std::endl;
            m_left_injector.reset();
            m_right_injector.reset();
            std::exit(1);
        }

        // Use the OpenXR runtime clock for injection time so it aligns with the
        // runtime's own time domain (XrTime), rather than a raw steady_clock cast.
        XrTime time = m_time_converter->os_monotonic_now();


        bool rigth_published = false;
        if (right_tracked.data)
        {
            Haptikos::HandData right_data = m_client.GetData(true, Haptikos::GlobalToWrist, true, true, false);
            bool valid_wrist = false;
            XrPosef rigth_controller = oxr_utils::get_aim_pose(*right_tracked.data, valid_wrist);

            if (right_data.IsValid() == 1 && valid_wrist)
            {
                calculate_hand_pose(right_joints, right_data, rigth_controller);
                if (!m_right_injector)
                {
                    const auto handles = m_session->get_handles();
                    m_right_injector = std::make_unique<plugin_utils::HandInjector>(
                        handles.instance, handles.session, XR_HAND_RIGHT_EXT, handles.space);
                }

                m_right_injector->push(right_joints, time);
                rigth_published = true;
            }
        }


        if (!rigth_published && m_right_injector)
        {
            m_right_injector.reset();
        }


        bool left_published = false;
        if (left_tracked.data)
        {
            Haptikos::HandData left_data = m_client.GetData(false, Haptikos::GlobalToWrist, true, true, false);
            bool valid_wrist = false;
            XrPosef left_controller = oxr_utils::get_aim_pose(*left_tracked.data, valid_wrist);

            if (left_data.IsValid() == 1 && valid_wrist)
            {
                calculate_hand_pose(left_joints, left_data, left_controller);

                if (!m_left_injector)
                {
                    const auto handles = m_session->get_handles();
                    m_left_injector = std::make_unique<plugin_utils::HandInjector>(
                        handles.instance, handles.session, XR_HAND_LEFT_EXT, handles.space);
                }
                m_left_injector->push(left_joints, time);
                left_published = true;
            }
        }

        if (!left_published && m_left_injector)
        {
            m_left_injector.reset();
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
