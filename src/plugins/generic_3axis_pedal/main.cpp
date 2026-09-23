// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "generic_3axis_pedal_plugin.hpp"

#include <log_bridge/logger.hpp>

#include <chrono>
#include <cstddef>
#include <iostream>
#include <string>
#include <thread>

using namespace plugins::generic_3axis_pedal;

int main(int argc, char** argv)
try
{
    auto logger = isaaccapture::Logger::get("isaaccapture.plugins.generic_3axis_pedal.main");

    if (argc == 0)
    {
        // Usage text is terminal UX, not a diagnostic, and the other plugin
        // mains in this tree print it the same way. A logger would also hide
        // it outright under ISAACCAPTURE_LOG_SOCKET, where local_sinks()
        // carries a forwarding sink and no console sink.
        std::cout << "Usage: generic_3axis_pedal <device_path> <collection_id>" << std::endl;
        return 1;
    }

    const std::string device_path = (argc > 1) ? argv[1] : "/dev/input/js0";
    const std::string collection_id = (argc > 2) ? argv[2] : "generic_3axis_pedal";

    logger->info("Generic 3-Axis Pedal (device: {}, collection: {})", device_path, collection_id);

    Generic3AxisPedalPlugin plugin(device_path, collection_id);

    // Push data at 90 Hz
    // TODO: Make the device push rate configurable
    const auto frame_duration = std::chrono::nanoseconds(1000000000 / 90);
    const auto program_start = std::chrono::steady_clock::now();
    std::size_t frame_count = 0;

    while (true)
    {
        plugin.update();
        frame_count++;
        std::this_thread::sleep_until(program_start + frame_duration * frame_count);
    }

    return 0;
}
catch (const std::exception& e)
{
    auto logger = isaaccapture::Logger::get("isaaccapture.plugins.generic_3axis_pedal.main");
    logger->error("{}: {}", argv[0], e.what());
    return 1;
}
catch (...)
{
    auto logger = isaaccapture::Logger::get("isaaccapture.plugins.generic_3axis_pedal.main");
    logger->error("{}: Unknown error", argv[0]);
    return 1;
}
