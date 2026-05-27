// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <core/haply_hand_tracking_plugin.hpp>

#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <thread>

using namespace plugins::haply;

namespace
{
std::atomic<bool> g_should_exit{ false };

void signal_handler(int)
{
    g_should_exit.store(true);
}
} // namespace

int main(int argc, char** argv)
try
{
    std::cout << "Haply Hand Plugin starting..." << std::endl;

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    auto& tracker = HaplyTracker::instance();

    std::cout << "Plugin running. Press Ctrl+C to stop." << std::endl;

    // Target 90Hz frequency (~11.1ms period)
    const auto target_frame_duration = std::chrono::nanoseconds(1000000000 / 90);

    while (!g_should_exit.load())
    {
        auto frame_start = std::chrono::steady_clock::now();

        tracker.update();

        std::this_thread::sleep_until(frame_start + target_frame_duration);
    }

    std::cout << "Haply Hand Plugin shutting down." << std::endl;
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
