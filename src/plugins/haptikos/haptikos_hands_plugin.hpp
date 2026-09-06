// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once

#include <deviceio_trackers/controller_tracker.hpp>
#include <openxr/openxr.h>
#include <pusherio/hand_tracking_pusher.hpp>
#include <pusherio/plugin_session.hpp>

#include <Client.hpp>
#include <atomic>
#include <memory>
#include <string>
#include <thread>


namespace plugins
{
namespace haptikos
{
class HaptikosHandsPlugin
{

public:
    HaptikosHandsPlugin(const std::string& plugin_root_id,
                        std::shared_ptr<core::ControllerTracker> controller_tracker,
                        core::PluginSessionHandle plugin_session) noexcept(false);
    ~HaptikosHandsPlugin();

    HaptikosHandsPlugin(const HaptikosHandsPlugin&) = delete;
    HaptikosHandsPlugin& operator=(const HaptikosHandsPlugin&) = delete;
    HaptikosHandsPlugin(const HaptikosHandsPlugin&&) = delete;
    HaptikosHandsPlugin& operator=(const HaptikosHandsPlugin&&) = delete;

private:
    void worker_thread();

    std::shared_ptr<core::ControllerTracker> m_controller_tracker;
    core::PluginSessionHandle m_plugin_session;
    std::unique_ptr<core::IPluginPullChannel> m_pull_channel;
    std::unique_ptr<core::HandTrackingPusher> m_left_pusher;
    std::unique_ptr<core::HandTrackingPusher> m_right_pusher;

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
