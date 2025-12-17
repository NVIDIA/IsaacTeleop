// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <core/manus_hand_tracking_plugin.hpp>

#include <algorithm>
#include <chrono>
#include <csignal>
#include <iomanip>
#include <iostream>
#include <thread>
#include <vector>

static volatile std::sig_atomic_t g_should_exit = 0;

static void handle_signal(int)
{
    g_should_exit = 1;
}

int main(int argc, char** argv)
{
    (void)argc;
    (void)argv;

    std::signal(SIGINT, handle_signal);
    std::signal(SIGTERM, handle_signal);

    std::cout << "Initializing Manus Tracker..." << std::endl;

    // Initialize the Manus tracker
    plugins::manus::ManusTracker* tracker_ptr = nullptr;
    try
    {
        tracker_ptr = &plugins::manus::ManusTracker::instance("ManusHandPrinter");
    }
    catch (const std::exception& e)
    {
        std::cerr << "Failed to initialize Manus tracker: " << e.what() << std::endl;
        return 1;
    }
    auto& tracker = *tracker_ptr;

    std::cout << "Press Ctrl+C to stop. Printing joint data..." << std::endl;

    int frame = 0;
    while (!g_should_exit)
    {
        // Get glove data from Manus SDK
        auto left_nodes = tracker.get_left_hand_nodes();
        auto right_nodes = tracker.get_right_hand_nodes();

        if (left_nodes.empty() && right_nodes.empty())
        {
            std::cout << "No data available yet..." << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            continue;
        }

        std::cout << "\n=== Frame " << frame << " ===" << std::endl;

        // Helper lambda to print hand data
        auto print_hand = [](const std::string& side, const std::vector<SkeletonNode>& nodes)
        {
            if (nodes.empty())
            {
                return;
            }

            std::cout << "\n" << side << " hand (" << nodes.size() << " joints):" << std::endl;

            for (size_t i = 0; i < std::min(nodes.size(), static_cast<size_t>(5)); ++i)
            {
                const auto& pos = nodes[i].transform.position;
                const auto& ori = nodes[i].transform.rotation;

                std::cout << "  Joint " << i << ": "
                          << "pos=[" << std::fixed << std::setprecision(3) << pos.x << ", " << pos.y << ", " << pos.z
                          << "] "
                          << "ori=[" << ori.x << ", " << ori.y << ", " << ori.z << ", " << ori.w << "]" << std::endl;
            }

            if (nodes.size() > 5)
            {
                std::cout << "  ... (" << (nodes.size() - 5) << " more joints)" << std::endl;
            }
        };

        print_hand("left", left_nodes);
        print_hand("right", right_nodes);

        std::cout << std::flush;

        frame++;
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }

    std::cout << "\nShutdown complete." << std::endl;
    return 0;
}
