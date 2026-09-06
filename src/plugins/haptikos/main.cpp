// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "haptikos_hands_plugin.hpp"

#include <deviceio_trackers/controller_tracker.hpp>
#include <deviceio_trackers/hand_tracker.hpp>
#include <plugin_utils/openxr_plugin_session.hpp>

#include <atomic>
#include <csignal>
#include <cstring>
#include <iostream>
#include <memory>
#include <thread>
#include <utility>
#include <vector>

using namespace plugins::haptikos;

static_assert(ATOMIC_BOOL_LOCK_FREE, "lock-free atomic bool is required for signal safety");

// Use atomic<bool> with relaxed ordering for signal safety
// Relaxed is sufficient since we only need atomicity, not synchronization
std::atomic<bool> g_stop_requested{ false };

void signal_handler(int signal)
{
    if (signal == SIGINT)
    {
        // Note: std::cout is not signal-safe, but atomic operations with relaxed ordering are
        g_stop_requested.store(true, std::memory_order_relaxed);
    }
}

int main(int argc, char** argv)
try
{
    std::string plugin_root_id = "haptikos_hands";

    // Parse command line arguments
    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if (arg.find("--plugin-root-id=") == 0)
        {
            plugin_root_id = arg.substr(17); // Length of "--plugin-root-id="
        }
    }

    std::signal(SIGINT, signal_handler);

    std::cout << "Haptikos Hands Plugin" << std::endl;
    std::cout << "Plugin Root ID: " << plugin_root_id << std::endl;

    auto controller_tracker = std::make_shared<core::ControllerTracker>();
    auto hand_tracker = std::make_shared<core::HandTracker>();
    std::vector<std::shared_ptr<core::ITracker>> trackers = { controller_tracker, std::move(hand_tracker) };
    core::PluginSessionHandle session = std::make_shared<plugin_utils::OpenXRPluginSession>(
        "HaptikosHands", core::PluginSessionRequirements{ .hand_tracking_push = true }, std::move(trackers));
    auto plugin =
        std::make_unique<HaptikosHandsPlugin>(plugin_root_id, std::move(controller_tracker), std::move(session));

    std::cout << "Plugin running. Press Ctrl+C to stop." << std::endl;
    while (!g_stop_requested.load(std::memory_order_relaxed))
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    // RAII: plugin stops in destructor when unique_ptr goes out of scope

    return 0;
}
catch (const std::exception& e)
{
    std::cerr << argv[0] << ": " << e.what() << std::endl;
    return 1;
}
catch (...)
{
    std::cerr << argv[0] << ": Unknown error occurred" << std::endl;
    return 1;
}
