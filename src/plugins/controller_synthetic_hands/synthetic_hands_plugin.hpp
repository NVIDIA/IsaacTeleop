// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#pragma once
#include "hand_generator.hpp"

#include <deviceio_trackers/controller_tracker.hpp>
#include <pusherio/hand_tracking_pusher.hpp>
#include <pusherio/plugin_session.hpp>

#include <atomic>
#include <memory>
#include <mutex>
#include <string>
#include <thread>

namespace plugins
{
namespace controller_synthetic_hands
{

class SyntheticHandsPlugin
{
public:
    SyntheticHandsPlugin(const std::string& plugin_root_id,
                         std::shared_ptr<core::ControllerTracker> controller_tracker,
                         core::PluginSessionHandle plugin_session) noexcept(false);
    ~SyntheticHandsPlugin();

    SyntheticHandsPlugin(const SyntheticHandsPlugin&) = delete;
    SyntheticHandsPlugin& operator=(const SyntheticHandsPlugin&) = delete;
    SyntheticHandsPlugin(SyntheticHandsPlugin&&) = delete;
    SyntheticHandsPlugin& operator=(SyntheticHandsPlugin&&) = delete;

private:
    void worker_thread();

    std::shared_ptr<core::ControllerTracker> m_controller_tracker;
    core::PluginSessionHandle m_plugin_session;
    std::unique_ptr<core::IPluginPullChannel> m_pull_channel;
    std::unique_ptr<core::HandTrackingPusher> m_left_pusher;
    std::unique_ptr<core::HandTrackingPusher> m_right_pusher;
    HandGenerator m_hand_gen;

    std::thread m_thread;
    std::atomic<bool> m_running{ false };
    std::atomic<bool> m_left_enabled{ true };
    std::atomic<bool> m_right_enabled{ true };

    std::string m_root_id;

    // Current state
    std::mutex m_state_mutex;
    float m_left_curl = 0.0f;
    float m_right_curl = 0.0f;
};

} // namespace controller_synthetic_hands
} // namespace plugins
