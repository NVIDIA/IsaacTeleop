// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "so101_leader_plugin.hpp"

#include <log_bridge/logger.hpp>

#include <chrono>
#include <cstddef>
#include <string>
#include <thread>

using namespace plugins::so101_leader;

int main(int argc, char** argv)
try
{
    // Calibration/dump mode: so101_leader_plugin calibrate <device_path> [output_file]
    // Reads the current servo positions (hold the arm at its zero pose) and optionally writes a
    // calibration file. No OpenXR runtime required.
    if (argc > 1 && std::string(argv[1]) == "calibrate")
    {
        const std::string device_path = (argc > 2) ? argv[2] : "";
        const std::string output_path = (argc > 3) ? argv[3] : "";
        return run_calibration(device_path, output_path);
    }

    // Usage: so101_leader_plugin [device_path] [collection_id] [calibration_file]
    // Empty device_path selects the synthetic backend (no hardware required).
    const std::string device_path = (argc > 1) ? argv[1] : "";
    const std::string collection_id = (argc > 2) ? argv[2] : "so101_leader";
    const std::string calibration_path = (argc > 3) ? argv[3] : "";

    isaacteleop::Logger::get("isaacteleop.plugins.so101_leader.main")
        ->info("SO-101 Leader Arm (device: {}, collection: {}{})", device_path.empty() ? "<synthetic>" : device_path,
               collection_id, calibration_path.empty() ? "" : ", calibration: " + calibration_path);

    So101LeaderPlugin plugin(device_path, collection_id, calibration_path);

    // Push joint state at 90 Hz.
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
    isaacteleop::Logger::get("isaacteleop.plugins.so101_leader.main")->error("{}: {}", argv[0], e.what());
    return 1;
}
catch (...)
{
    isaacteleop::Logger::get("isaacteleop.plugins.so101_leader.main")->error("{}: Unknown error", argv[0]);
    return 1;
}
