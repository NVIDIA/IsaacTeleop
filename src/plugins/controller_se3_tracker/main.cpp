// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "controller_se3_tracker_plugin.hpp"

#include <deviceio_trackers/se3_tracker.hpp>

#include <chrono>
#include <cstddef>
#include <iostream>
#include <string>
#include <thread>

using namespace plugins::controller_se3_tracker;

int main(int argc, char** argv)
try
{
    const std::string hand = (argc > 1) ? argv[1] : "right";
    // The default collection id deliberately matches the tensor identifier so plugin and
    // Se3Tracker rendezvous out of the box (see README).
    const std::string collection_id = (argc > 2) ? argv[2] : std::string(core::Se3Tracker::TENSOR_IDENTIFIER);

    if (hand != "left" && hand != "right")
    {
        std::cerr << "Usage: " << argv[0] << " [hand(left|right)] [collection_id]" << std::endl;
        return 1;
    }

    std::cout << "Controller SE3 Tracker (hand: " << hand << ", collection: " << collection_id << ")" << std::endl;

    ControllerSe3TrackerPlugin plugin(hand == "left", collection_id);

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
