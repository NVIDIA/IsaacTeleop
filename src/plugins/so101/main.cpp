// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "so101/so101_plugin.hpp"

#include <chrono>
#include <cstddef>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

using namespace plugins::so101;

int main(int argc, char** argv)
try
{
    // Configuration via environment variables with command-line override
    const char* env_port = std::getenv("SO101_SERIAL_PORT");
    const char* env_baud = std::getenv("SO101_BAUDRATE");
    const char* env_collection = std::getenv("SO101_COLLECTION_ID");

    const std::string device_port = (argc > 1) ? argv[1] : (env_port ? env_port : "/dev/ttyACM0");
    const int baudrate = (argc > 2) ? std::atoi(argv[2]) : (env_baud ? std::atoi(env_baud) : 1000000);
    const std::string collection_id = (argc > 3) ? argv[3] : (env_collection ? env_collection : "so101_leader");

    std::cout << "SO-101 Arm Plugin (port: " << device_port << ", baud: " << baudrate
              << ", collection: " << collection_id << ")" << std::endl;

    SO101Plugin plugin(device_port, collection_id, baudrate);

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
    std::cerr << argv[0] << ": " << e.what() << std::endl;
    return 1;
}
catch (...)
{
    std::cerr << argv[0] << ": Unknown error" << std::endl;
    return 1;
}
