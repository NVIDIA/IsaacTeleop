// SPDX-FileCopyrightText: Copyright (c) 2026 Wuji Technology. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "wuji_glove_plugin.hpp"

#include <log_bridge/logger.hpp>

#include <atomic>
#include <chrono>
#include <csignal>
#include <memory>
#include <string>
#include <thread>

using namespace plugins::wuji_glove;

// == 2 means "always lock-free"; 1 only means "sometimes", which is not a
// guarantee the signal handler below can rely on.
static_assert(ATOMIC_BOOL_LOCK_FREE == 2, "lock-free atomic bool is required for signal safety");

std::atomic<bool> g_stop_requested{ false };

void signal_handler(int signal)
{
    if (signal == SIGINT || signal == SIGTERM)
    {
        g_stop_requested.store(true, std::memory_order_relaxed);
    }
}

int main(int argc, char** argv)
try
{
    std::string plugin_root_id = "wuji_glove";

    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if (arg.find("--plugin-root-id=") == 0)
        {
            plugin_root_id = arg.substr(17); // length of "--plugin-root-id="
        }
    }

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.wuji_glove.main");
    logger->info("Wuji Glove Plugin");
    logger->info("Plugin Root ID: {}", plugin_root_id);

    auto plugin = std::make_unique<WujiGlovePlugin>(plugin_root_id);

    logger->info("Plugin running. Press Ctrl+C to stop.");
    while (!g_stop_requested.load(std::memory_order_relaxed) && plugin->is_running())
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    const bool failed = plugin->has_failed();
    // RAII: plugin stops in destructor when unique_ptr goes out of scope.
    return failed ? 1 : 0;
}
catch (const std::exception& e)
{
    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.wuji_glove.main");
    logger->error("{}: {}", argv[0], e.what());
    return 1;
}
catch (...)
{
    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.wuji_glove.main");
    logger->error("{}: Unknown error occurred", argv[0]);
    return 1;
}
