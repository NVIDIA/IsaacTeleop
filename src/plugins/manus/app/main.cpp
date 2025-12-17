// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <manus_hand_tracking_plugin.hpp>
#include <thread>

using namespace plugins::manus;

// Use atomic<bool> with relaxed ordering for signal safety
std::atomic<bool> g_stop_requested{ false };

void signal_handler(int signal)
{
    if (signal == SIGINT)
    {
        g_stop_requested.store(true, std::memory_order_relaxed);
    }
}

int main(int argc, char** argv)
{
    std::signal(SIGINT, signal_handler);

    std::cout << "Manus Hand Plugin starting..." << std::endl;

    plugins::manus::ManusTracker* tracker_ptr = nullptr;
    try
    {
        tracker_ptr = &ManusTracker::instance();
    }
    catch (const std::exception& e)
    {
        std::cerr << "Failed to initialize Manus Hand Plugin: " << e.what() << std::endl;
        return 1;
    }

    auto& tracker = *tracker_ptr;

    std::cout << "Plugin running. Press Ctrl+C to stop." << std::endl;

    // Target 90Hz frequency (~11.1ms period)
    const auto target_frame_duration = std::chrono::nanoseconds(1000000000 / 90);

    while (!g_stop_requested.load(std::memory_order_relaxed))
    {
        auto frame_start = std::chrono::steady_clock::now();

        tracker.update();

        std::this_thread::sleep_until(frame_start + target_frame_duration);
    }

    std::cout << "Stopping..." << std::endl;

    return 0;
}
