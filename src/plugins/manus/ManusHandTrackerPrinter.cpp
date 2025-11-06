// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "ManusHandTrackingPlugin.h"

#include <chrono>
#include <csignal>
#include <iomanip>
#include <iostream>
#include <thread>

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
    isaacteleop::plugins::manus::ManusTracker tracker;
    if (!tracker.initialize())
    {
        std::cerr << "Failed to initialize Manus tracker." << std::endl;
        return 1;
    }

    std::cout << "Press Ctrl+C to stop. Printing joint data..." << std::endl;

    int frame = 0;
    while (!g_should_exit)
    {
        // Get glove data from Manus SDK
        auto glove_data = tracker.get_glove_data();

        if (glove_data.empty())
        {
            std::cout << "No data available yet..." << std::endl;
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            continue;
        }

        std::cout << "\n=== Frame " << frame << " ===" << std::endl;

        // Print data for each hand
        for (const auto& side : { "left", "right" })
        {
            std::string pos_key = std::string(side) + "_position";
            std::string ori_key = std::string(side) + "_orientation";

            if (glove_data.find(pos_key) != glove_data.end())
            {
                const auto& positions = glove_data[pos_key];
                const auto& orientations = glove_data[ori_key];

                int joint_count = positions.size() / 3;

                std::cout << "\n" << side << " hand (" << joint_count << " joints):" << std::endl;

                for (int i = 0; i < std::min(joint_count, 5); ++i)
                {
                    std::cout << "  Joint " << i << ": "
                              << "pos=[" << std::fixed << std::setprecision(3) << positions[i * 3 + 0] << ", "
                              << positions[i * 3 + 1] << ", " << positions[i * 3 + 2] << "] "
                              << "ori=[" << orientations[i * 4 + 0] << ", " << orientations[i * 4 + 1] << ", "
                              << orientations[i * 4 + 2] << ", " << orientations[i * 4 + 3] << "]" << std::endl;
                }

                if (joint_count > 5)
                {
                    std::cout << "  ... (" << (joint_count - 5) << " more joints)" << std::endl;
                }
            }
        }

        std::cout << std::flush;

        frame++;
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }

    tracker.cleanup();
    std::cout << "\nShutdown complete." << std::endl;
    return 0;
}
