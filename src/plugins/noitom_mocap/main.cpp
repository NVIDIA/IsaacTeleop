// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "noitom_mocap_plugin.hpp"

#include <atomic>
#include <chrono>
#include <csignal>
#include <cstdint>
#include <iostream>
#include <stdexcept>
#include <string>
#include <thread>

using namespace plugins::noitom_mocap;

namespace
{

std::atomic<bool> g_stop_requested{ false };

void signal_handler(int signal)
{
    if (signal == SIGINT || signal == SIGTERM)
    {
        g_stop_requested.store(true, std::memory_order_relaxed);
    }
}

void print_usage(const char* program_name)
{
    std::cout << "Usage: " << program_name << " [options]\n"
              << "\nConnection:\n"
              << "  --protocol=tcp|udp        Noitom HDS connection mode (default: tcp)\n"
              << "  --host=ADDR               TCP server address (default: 127.0.0.1)\n"
              << "  --port=N                  TCP server port (default: 8001)\n"
              << "  --udp-local-port=N        UDP local listen port (default: 8002)\n"
              << "  --udp-server-host=ADDR    Optional UDP server address\n"
              << "  --udp-server-port=N       Optional UDP server port (default: 8001)\n"
              << "\nDeviceIO:\n"
              << "  --collection-id=ID        Tensor collection id (default: noitom_mocap)\n"
              << "  --max-flatbuffer-size=N   Max serialized frame size (default: "
              << DEFAULT_NOITOM_MOCAP_MAX_FLATBUFFER_SIZE << ")\n"
              << "  --rate=N                  Poll loop rate in Hz (default: 90)\n"
              << "\nGeneral:\n"
              << "  --help                    Show this message\n";
}

uint16_t parse_u16(const std::string& value, const std::string& name)
{
    int parsed = std::stoi(value);
    if (parsed < 0 || parsed > 65535)
    {
        throw std::runtime_error(name + " must fit uint16");
    }
    return static_cast<uint16_t>(parsed);
}

} // namespace

int main(int argc, char** argv)
try
{
    NoitomMocapPluginConfig config;
    double rate_hz = 90.0;

    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];
        if (arg == "--help" || arg == "-h")
        {
            print_usage(argv[0]);
            return 0;
        }
        if (arg == "--plugin-root-id")
        {
            if (i + 1 >= argc)
            {
                throw std::runtime_error("--plugin-root-id requires a value");
            }
            ++i;
            continue;
        }
        if (arg.find("--protocol=") == 0)
        {
            std::string value = arg.substr(11);
            if (value == "tcp")
                config.protocol = MocapProtocol::Tcp;
            else if (value == "udp")
                config.protocol = MocapProtocol::Udp;
            else
                throw std::runtime_error("--protocol must be tcp or udp");
        }
        else if (arg.find("--host=") == 0)
        {
            config.host = arg.substr(7);
        }
        else if (arg.find("--port=") == 0)
        {
            config.port = parse_u16(arg.substr(7), "--port");
        }
        else if (arg.find("--udp-local-port=") == 0)
        {
            config.udp_local_port = parse_u16(arg.substr(17), "--udp-local-port");
        }
        else if (arg.find("--udp-server-host=") == 0)
        {
            config.udp_server_host = arg.substr(18);
        }
        else if (arg.find("--udp-server-port=") == 0)
        {
            config.udp_server_port = parse_u16(arg.substr(18), "--udp-server-port");
        }
        else if (arg.find("--collection-id=") == 0)
        {
            config.collection_id = arg.substr(16);
        }
        else if (arg.find("--max-flatbuffer-size=") == 0)
        {
            config.max_flatbuffer_size = static_cast<size_t>(std::stoull(arg.substr(22)));
        }
        else if (arg.find("--rate=") == 0)
        {
            rate_hz = std::stod(arg.substr(7));
            if (rate_hz <= 0.0)
            {
                throw std::runtime_error("--rate must be positive");
            }
        }
        else if (arg.find("--plugin-root-id=") == 0)
        {
            continue;
        }
        else
        {
            std::cerr << "Unknown option: " << arg << std::endl;
            print_usage(argv[0]);
            return 1;
        }
    }

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    NoitomMocapPlugin plugin(config);

    const auto frame_duration = std::chrono::nanoseconds(static_cast<int64_t>(1000000000.0 / rate_hz));
    const auto program_start = std::chrono::steady_clock::now();
    std::size_t frame_count = 0;

    while (!g_stop_requested.load(std::memory_order_relaxed))
    {
        if (!plugin.update())
        {
            return 1;
        }
        ++frame_count;
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
