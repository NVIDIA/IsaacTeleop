// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "manus_hand_visualizer.hpp"

#include <log_bridge/logger.hpp>
#include <manus/manus_hand_tracking_plugin.hpp>

#include <algorithm>
#include <chrono>
#include <thread>
#include <vector>

int main(int argc, char** argv)
try
{
    (void)argc;
    (void)argv;

    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.manus.manus_hand_tracker_printer");
    logger->info("Initializing Manus Tracker...");

    plugins::manus::ManusPluginConfig config;
    config.app_name = "ManusHandPrinter";
    auto& tracker = plugins::manus::ManusTracker::instance(config);

    // Start Vulkan visualizer in a background thread.
    // If X11 or Vulkan is unavailable the thread exits cleanly and printing
    // continues without the window.
    // std::jthread automatically requests stop and joins on destruction,
    // preventing the thread from outliving the tracker singleton.
    std::jthread vis_thread(
        [&tracker, logger](std::stop_token st)
        {
            try
            {
                plugins::manus::HandVisualizer vis;
                vis.run(tracker, std::move(st));
            }
            catch (const std::exception& e)
            {
                logger->warn("Visualizer failed: {} — running without visualizer", e.what());
            }
        });

    logger->info("Press Ctrl+C to stop. Printing joint data...");

    int frame = 0;
    bool waiting_printed = false;
    while (true)
    {
        // Get glove data from Manus SDK
        auto left_nodes = tracker.get_left_hand_nodes();
        auto right_nodes = tracker.get_right_hand_nodes();

        if (left_nodes.empty() && right_nodes.empty())
        {
            if (!waiting_printed)
            {
                logger->info("Waiting for gloves...");
                waiting_printed = true;
            }
            std::this_thread::sleep_for(std::chrono::milliseconds(200));
            continue;
        }
        waiting_printed = false;

        logger->info("=== Frame {} ===", frame);

        // Helper lambda to print hand data
        auto print_hand = [logger](const std::string& side, const std::vector<SkeletonNode>& nodes)
        {
            if (nodes.empty())
            {
                return;
            }

            logger->info("{} hand ({} joints):", side, nodes.size());

            for (size_t i = 0; i < std::min(nodes.size(), static_cast<size_t>(5)); ++i)
            {
                const auto& pos = nodes[i].transform.position;
                const auto& ori = nodes[i].transform.rotation;

                logger->info("  Joint {}: pos=[{:.3f}, {:.3f}, {:.3f}] ori=[{:.3f}, {:.3f}, {:.3f}, {:.3f}]", i, pos.x,
                             pos.y, pos.z, ori.x, ori.y, ori.z, ori.w);
            }

            if (nodes.size() > 5)
            {
                logger->info("  ... ({} more joints)", nodes.size() - 5);
            }
        };

        print_hand("left", left_nodes);
        print_hand("right", right_nodes);

        frame++;
        std::this_thread::sleep_for(std::chrono::milliseconds(500));
    }

    return 0;
}
catch (const std::exception& e)
{
    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.manus.manus_hand_tracker_printer");
    logger->error("{}: {}", argv[0], e.what());
    return 1;
}
catch (...)
{
    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.manus.manus_hand_tracker_printer");
    logger->error("{}: Unknown error occurred", argv[0]);
    return 1;
}
