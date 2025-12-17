// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <csignal>
#include <cstring>
#include <iostream>
#include <memory>
#include <synthetic_hands_plugin.hpp>

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
{
    std::string plugin_root_id = "synthetic_hands";

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

    std::cout << "Controller Synthetic Hands Plugin" << std::endl;
    std::cout << "Plugin Root ID: " << plugin_root_id << std::endl;

    std::unique_ptr<SyntheticHandsPlugin> plugin;
    try
    {
        plugin = std::make_unique<SyntheticHandsPlugin>(plugin_root_id);
    }
    catch (const std::exception& e)
    {
        std::cerr << "Failed to create plugin: " << e.what() << std::endl;
        return 1;
    }

    std::cout << "Plugin running. Press Ctrl+C to stop." << std::endl;
    while (!g_stop_requested.load(std::memory_order_relaxed))
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    // RAII: plugin stops in destructor when unique_ptr goes out of scope

    return 0;
}
