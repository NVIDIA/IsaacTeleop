// SPDX-FileCopyrightText: Copyright (c) 2026 HTC Corporation. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "vive_se3_tracker_plugin.hpp"

#include <log_bridge/logger.hpp>

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstddef>
#include <thread>

using namespace plugins::vive_se3_tracker;

namespace
{
std::atomic<bool> g_stop{ false };
void on_signal(int)
{
    g_stop.store(true);
}
} // namespace

int main(int, char** argv)
try
{
    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.vive_se3_tracker.main");
    logger->info("Vive SE3 Tracker Plugin (one collection per Ultimate Tracker)");

    // Stop cleanly on Ctrl+C / kill so ~ViveSe3TrackerPlugin runs and removes the
    // collections advertisement file (else readers see stale collection ids).
    std::signal(SIGINT, on_signal);
    std::signal(SIGTERM, on_signal);

    ViveSe3TrackerPlugin plugin;

    // Poll/push at 90 Hz; valid samples carry the VUT sample time, so the loop
    // rate only bounds delivery latency, not timestamp accuracy.
    const auto frame_duration = std::chrono::nanoseconds(1000000000 / 90);
    const auto program_start = std::chrono::steady_clock::now();
    std::size_t frame_count = 0;

    while (!g_stop.load())
    {
        plugin.update();
        frame_count++;
        std::this_thread::sleep_until(program_start + frame_duration * frame_count);
    }

    logger->info("shutting down.");
    return 0;
}
catch (const std::exception& e)
{
    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.vive_se3_tracker.main");
    logger->error("{}: {}", argv[0], e.what());
    return 1;
}
catch (...)
{
    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.vive_se3_tracker.main");
    logger->error("{}: Unknown error", argv[0]);
    return 1;
}
