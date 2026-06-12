// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/controller_tracker.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <openxr/openxr.h>
#include <oxr/oxr_session.hpp>
#include <oxr_utils/oxr_time.hpp>
#include <plugin_utils/hand_injector.hpp>

#include <Client.hpp>
#include <atomic>
#include <thread>


namespace plugins
{
namespace haptikos
{
class HaptikosHandsPlugin
{

public:
    HaptikosHandsPlugin(const std::string& plugin_root_id) noexcept(false);
    ~HaptikosHandsPlugin();

    HaptikosHandsPlugin(const HaptikosHandsPlugin&) = delete;
    HaptikosHandsPlugin& operator=(const HaptikosHandsPlugin&) = delete;
    HaptikosHandsPlugin(const HaptikosHandsPlugin&&) = delete;
    HaptikosHandsPlugin& operator=(const HaptikosHandsPlugin&&) = delete;

private:
    void worker_thread();

    // OpenXR State
    std::shared_ptr<core::OpenXRSession> m_session;
    std::unique_ptr<plugin_utils::HandInjector> m_left_injector;
    std::unique_ptr<plugin_utils::HandInjector> m_right_injector;
    std::optional<core::XrTimeConverter> m_time_converter;
    std::shared_ptr<core::ControllerTracker> m_controller_tracker;
    std::shared_ptr<core::HandTracker> m_hand_tracker;
    std::unique_ptr<core::DeviceIOSession> m_deviceio_session;


    std::string m_root_id;
    Haptikos::Client m_client;

    std::thread m_thread;
    std::atomic<bool> m_running{ false };

    void calculate_hand_pose(XrHandJointLocationEXT* result, const Haptikos::HandData& data, const XrPosef& wrist_pose);

    // Handles casting and converting to the OpenXR coordinate system
    XrPosef get_pose(const Haptikos::Vector3& position, const Haptikos::Quaternion& rotation);
};

} // namespace haptikos
} // namespace plugins
