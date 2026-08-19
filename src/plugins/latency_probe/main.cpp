// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "latency_probe_plugin.hpp"

#include <chrono>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

using namespace plugins::latency_probe;

namespace
{

void print_usage(const char* program)
{
    std::cerr << "Usage: " << program << " [in_collection] [out_collection]\n"
              << "  Defaults: latency_probe_in latency_probe_out\n"
              << "  --plugin-root-id=... is injected by PluginManager and ignored.\n";
}

} // namespace

int main(int argc, char** argv)
try
{
    std::vector<std::string> positionals;
    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];
        if (arg.starts_with("--plugin-root-id="))
        {
            continue;
        }
        if (arg.starts_with("--"))
        {
            std::cerr << "Unknown option: " << arg << std::endl;
            print_usage(argv[0]);
            return 1;
        }
        positionals.push_back(arg);
    }

    if (positionals.size() > 2)
    {
        std::cerr << "Too many positional arguments." << std::endl;
        print_usage(argv[0]);
        return 1;
    }

    const std::string in_collection = !positionals.empty() ? positionals[0] : "latency_probe_in";
    const std::string out_collection = positionals.size() > 1 ? positionals[1] : "latency_probe_out";

    std::cout << "Latency probe plugin (in=" << in_collection << ", out=" << out_collection << ")" << std::endl;

    LatencyProbePlugin plugin(in_collection, out_collection);

    constexpr int frame_rate_hz = 60;
    const auto frame_duration = std::chrono::nanoseconds(1'000'000'000 / frame_rate_hz);
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
