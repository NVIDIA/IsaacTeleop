// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "so101_leader_plugin.hpp"

#include <chrono>
#include <cstddef>
#include <iostream>
#include <string>
#include <thread>

using namespace plugins::so101_leader;

int main(int argc, char** argv)
try
{
    // Usage: so101_leader_plugin [device_path] [collection_id] [calibration_file]
    // Empty device_path selects the synthetic backend (no hardware required).
    const std::string device_path = (argc > 1) ? argv[1] : "";
    const std::string collection_id = (argc > 2) ? argv[2] : "so101_leader";
    const std::string calibration_path = (argc > 3) ? argv[3] : "";

    std::cout << "SO-101 Leader Arm (device: " << (device_path.empty() ? "<synthetic>" : device_path)
              << ", collection: " << collection_id
              << (calibration_path.empty() ? "" : ", calibration: " + calibration_path) << ")" << std::endl;

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
    std::cerr << argv[0] << ": " << e.what() << std::endl;
    return 1;
}
catch (...)
{
    std::cerr << argv[0] << ": Unknown error" << std::endl;
    return 1;
}
