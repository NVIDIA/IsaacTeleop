// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <core/haply_plugin.hpp>

#include <chrono>
#include <cstdlib>
#include <iostream>
#include <string>
#include <thread>

using namespace plugins::haply;

int main(int argc, char** argv)
try
{
    const char* env_collection = std::getenv("HAPLY_COLLECTION_ID");
    const std::string collection_id = (argc > 1) ? argv[1] : (env_collection ? env_collection : "haply_device");

    std::cout << "Haply Device Plugin (collection: " << collection_id << ")" << std::endl;

    HaplyPlugin plugin(collection_id);

    // Push data at 90 Hz
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
