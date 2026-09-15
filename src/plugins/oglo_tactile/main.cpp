// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oglo_tactile_plugin.hpp"

#include <log_bridge/logger.hpp>

#include <atomic>
#include <csignal>
#include <cstddef>
#include <iostream>
#include <string>

using namespace plugins::oglo_tactile;

namespace
{

std::atomic<bool> g_stop{ false };

void signal_handler(int signal)
{
    if (signal == SIGINT || signal == SIGTERM)
        g_stop.store(true, std::memory_order_relaxed);
}

void print_usage(const char* prog)
{
    std::cout << "Usage: " << prog << " --side left|right --collection-prefix=PREFIX [options]\n"
              << "\nRequired:\n"
              << "  --side left|right            Hand to connect (selects OGLO LEFT/RIGHT)\n"
              << "  --collection-prefix=PREFIX   Push via OpenXR for a host tracker\n"
              << "\nOptional:\n"
              << "  --device-name=NAME           Pin an exact advertised BLE name\n"
              << "  --scan-timeout-ms=N          Scan timeout (default 15000)\n"
              << "  --help                       Show this help\n";
}

} // namespace

int main(int argc, char** argv)
try
{
    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.oglo_tactile.main");

    OgloTactilePlugin::Options opts;
    bool side_set = false;

    for (int i = 1; i < argc; ++i)
    {
        const std::string arg = argv[i];
        if (arg == "--help" || arg == "-h")
        {
            print_usage(argv[0]);
            return 0;
        }
        else if (arg.rfind("--side=", 0) == 0 || arg == "--side")
        {
            const std::string val = (arg == "--side") ? (i + 1 < argc ? argv[++i] : "") : arg.substr(7);
            opts.side = side_from_string(val);
            side_set = true;
        }
        else if (arg.rfind("--collection-prefix=", 0) == 0)
        {
            opts.collection_prefix = arg.substr(20);
        }
        else if (arg.rfind("--device-name=", 0) == 0)
        {
            opts.device_name_override = arg.substr(14);
        }
        else if (arg.rfind("--scan-timeout-ms=", 0) == 0)
        {
            const std::string val = arg.substr(18);
            int ms = 0;
            try
            {
                std::size_t parsed = 0;
                ms = std::stoi(val, &parsed);
                if (parsed != val.size())
                    ms = -1; // reject trailing garbage, e.g. "15000ms"
            }
            catch (const std::exception&)
            {
                ms = -1; // force the validation error below
            }
            if (ms <= 0)
            {
                logger->error("--scan-timeout-ms expects a positive integer (got '{}').", val);
                print_usage(argv[0]);
                return 1;
            }
            opts.scan_timeout = std::chrono::milliseconds(ms);
        }
        else if (arg.rfind("--plugin-root-id=", 0) == 0)
        {
            // Injected by the PluginManager; not needed here.
        }
        else
        {
            logger->error("Unknown option: {}", arg);
            print_usage(argv[0]);
            return 1;
        }
    }

    if (!side_set || opts.side == Side::Unknown)
    {
        logger->error("--side left|right is required.");
        print_usage(argv[0]);
        return 1;
    }

    if (opts.collection_prefix.empty())
    {
        logger->error("--collection-prefix=PREFIX is required.");
        print_usage(argv[0]);
        return 1;
    }

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    logger->info("OGLO Tactile Glove Plugin ({})", to_string(opts.side));

    OgloTactilePlugin plugin(std::move(opts));
    plugin.run(g_stop);

    return 0;
}
catch (const std::exception& e)
{
    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.oglo_tactile.main");
    logger->error("{}: {}", argv[0], e.what());
    return 1;
}
catch (...)
{
    auto logger = isaacteleop::Logger::get("isaacteleop.plugins.oglo_tactile.main");
    logger->error("{}: unknown error", argv[0]);
    return 1;
}
