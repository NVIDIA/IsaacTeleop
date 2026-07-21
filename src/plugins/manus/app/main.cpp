// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <manus/manus_hand_tracking_plugin.hpp>

#include <chrono>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include <thread>
#include <vector>

using namespace plugins::manus;

namespace
{

bool starts_with(const std::string& value, const std::string& prefix)
{
    return value.size() >= prefix.size() && value.compare(0, prefix.size(), prefix) == 0;
}

std::vector<std::string> split_csv(const std::string& text)
{
    std::vector<std::string> out;
    std::stringstream ss(text);
    std::string item;
    while (std::getline(ss, item, ','))
    {
        // Trim whitespace
        const auto start = item.find_first_not_of(" \t");
        if (start == std::string::npos)
        {
            continue;
        }
        const auto end = item.find_last_not_of(" \t");
        out.push_back(item.substr(start, end - start + 1));
    }
    return out;
}

ManusPluginConfig parse_args(int argc, char** argv)
{
    ManusPluginConfig config;
    std::string datasets_arg = "human,sensors,haptic";

    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];
        if (starts_with(arg, "--datasets="))
        {
            datasets_arg = arg.substr(std::string("--datasets=").size());
        }
        else if (starts_with(arg, "--plugin-root-id="))
        {
            // Injected by the PluginManager; not used by this plugin.
        }
        else
        {
            std::cerr << "ManusHandPlugin: ignoring unknown argument '" << arg << "'" << std::endl;
        }
    }

    config.human = false;
    config.sensors = false;
    config.haptic = false;
    for (const auto& ds : split_csv(datasets_arg))
    {
        if (ds == "human")
        {
            config.human = true;
        }
        else if (ds == "sensors")
        {
            config.sensors = true;
        }
        else if (ds == "haptic")
        {
            config.haptic = true;
        }
        else
        {
            std::cerr << "ManusHandPlugin: ignoring unknown data set '" << ds << "'" << std::endl;
        }
    }

    if (!config.human && !config.sensors && !config.haptic)
    {
        throw std::runtime_error("ManusHandPlugin: --datasets must enable at least one of human,sensors,haptic");
    }

    return config;
}

} // namespace

int main(int argc, char** argv)
try
{
    std::cout << "Manus Hand Plugin starting..." << std::endl;

    const ManusPluginConfig config = parse_args(argc, argv);
    auto& tracker = ManusTracker::instance(config);

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
