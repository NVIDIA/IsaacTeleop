// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <manus/manus_hand_tracking_plugin.hpp>

#include <chrono>
#include <iostream>
#include <string_view>
#include <thread>

using namespace plugins::manus;

int main(int argc, char** argv)
try
{
    std::cout << "Manus Hand Plugin starting..." << std::endl;

    bool disable_optical_wrist = false;
    for (int i = 1; i < argc; ++i)
    {
        const std::string_view arg(argv[i]);
        if (arg == "--disable-optical-wrist")
        {
            disable_optical_wrist = true;
        }
        else if (arg == "--help" || arg == "-h")
        {
            std::cout << "Usage: " << argv[0] << " [--disable-optical-wrist]\n";
            return 0;
        }
    }

    auto& tracker = ManusTracker::instance("ManusHandPlugin", disable_optical_wrist);

    std::cout << "Plugin running. Press Ctrl+C to stop." << std::endl;

    // Target 90Hz frequency (~11.1ms period)
    const auto target_frame_duration = std::chrono::nanoseconds(1000000000 / 90);

    while (true)
    {
        auto frame_start = std::chrono::steady_clock::now();

        tracker.update();

        std::this_thread::sleep_until(frame_start + target_frame_duration);
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
    std::cerr << argv[0] << ": Unknown error occurred" << std::endl;
    return 1;
}
