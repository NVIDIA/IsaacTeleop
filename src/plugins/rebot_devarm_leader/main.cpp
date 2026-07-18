// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "rebot_devarm_leader_plugin.hpp"

#include <chrono>
#include <cstddef>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

using namespace plugins::rebot_devarm_leader;

int main(int argc, char** argv)
try
{
    // Probe mode: rebot_devarm_leader_plugin probe <device_path> [calibration_file] [seconds]
    // <device_path> is a serial path (/dev/ttyACM0, Damiao build) or a SocketCAN interface
    // name (can0, RobStride build). Streams decoded joint positions to stdout to verify the
    // bus / ids / decoding. No OpenXR runtime required.
    if (argc > 1 && std::string(argv[1]) == "probe")
    {
        const std::string device_path = (argc > 2) ? argv[2] : "";
        const std::string calibration_path = (argc > 3) ? argv[3] : "";
        const int seconds = (argc > 4) ? std::atoi(argv[4]) : 3;
        return run_probe(device_path, calibration_path, seconds);
    }

    // Usage: rebot_devarm_leader_plugin [device_path] [collection_id] [calibration_file]
    // device_path: serial path (Damiao), SocketCAN interface name (RobStride), or empty for
    // the synthetic backend (no hardware required).
    const std::string device_path = (argc > 1) ? argv[1] : "";
    const std::string collection_id = (argc > 2) ? argv[2] : "rebot_devarm_leader";
    const std::string calibration_path = (argc > 3) ? argv[3] : "";

    std::cout << "reBot DevArm Leader (device: " << (device_path.empty() ? "<synthetic>" : device_path)
              << ", collection: " << collection_id
              << (calibration_path.empty() ? "" : ", calibration: " + calibration_path) << ")" << std::endl;

    RebotDevarmLeaderPlugin plugin(device_path, collection_id, calibration_path);

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
