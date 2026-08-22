// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "core/frame_sink.hpp"
#include "core/sensing_camera.hpp"

#include <atomic>
#include <chrono>
#include <cstdlib>
#include <csignal>
#include <iostream>
#include <map>
#include <sstream>
#include <string>
#include <thread>

using namespace plugins::sensing;

// =============================================================================
// Signal handling
// =============================================================================

static std::atomic<bool> g_stop_requested{ false };

void signal_handler(int signal)
{
    if (signal == SIGINT || signal == SIGTERM)
    {
        g_stop_requested.store(true, std::memory_order_relaxed);
    }
}

// =============================================================================
// --add-stream parser
// =============================================================================

static StreamConfig parse_stream_arg(const std::string& arg)
{
    StreamConfig cfg{};
    bool has_sensor = false;

    std::istringstream ss(arg);
    std::string token;
    while (std::getline(ss, token, ','))
    {
        auto eq = token.find('=');
        if (eq == std::string::npos)
            throw std::runtime_error("Invalid key=value in --add-stream: '" + token + "'");

        auto key = token.substr(0, eq);
        auto val = token.substr(eq + 1);

        if (key == "sensor")
        {
            cfg.sensor_id = static_cast<uint32_t>(std::stoul(val));
            has_sensor = true;
        }
        else if (key == "output")
        {
            cfg.output_path = val;
        }
        else if (key == "ipc")
        {
            cfg.ipc_socket_path = val;
        }
        else
        {
            throw std::runtime_error("Unknown key in --add-stream: '" + key + "'");
        }
    }

    if (!has_sensor)
        throw std::runtime_error("--add-stream requires sensor=<argus-sensor-id>");
    if (cfg.output_path.empty() && cfg.ipc_socket_path.empty())
        throw std::runtime_error("--add-stream requires output=<path> or ipc=<socket>, or both");

    return cfg;
}

// =============================================================================
// Usage
// =============================================================================

void print_usage(const char* program_name)
{
    std::cout << "Usage: " << program_name << " [options] --add-stream ...\n"
              << "\nStream Configuration (repeatable):\n"
              << "  --add-stream sensor=<id>[,output=<path>][,ipc=<socket>]\n"
              << "      sensor: Argus sensor id (device-tree module order, NOT /dev/videoN)\n"
              << "      output: file path for this stream's H.264 data\n"
              << "      ipc:    Unix socket serving raw RGBA8 frames as CUDA memory to\n"
              << "              another process (camera_viz `type: cuda_ipc`). No encode.\n"
              << "      At least one of output/ipc is required; both may be given.\n"
              << "\nGlobal Camera Settings:\n"
              << "  --sensor-mode=N     Argus sensor mode (default: 0; S56C has only 0, SHF3L uses 2)\n"
              << "  --width=N           Capture width (default: 1920)\n"
              << "  --height=N          Capture height (default: 1080)\n"
              << "  --fps=N             Frame rate for all streams (default: 30)\n"
              << "  --bitrate=N         H.264 bitrate in bps (default: 20000000)\n"
              << "  --gop=N             IDR period in frames (default: fps*5)\n"
              << "  --gpu-id=N          CUDA device index (default: 0)\n"
              << "  --full-range        Treat luma as full range instead of broadcast range\n"
              << "  --no-swap-uv        Do not swap the chroma planes\n"
              << "\nMetadata (mutually exclusive):\n"
              << "  --collection-prefix=PREFIX  Push metadata via OpenXR tensor extensions\n"
              << "  --mcap-filename=PATH        Record metadata to an MCAP file\n"
              << "\nGeneral:\n"
              << "  --help              Show this help message\n"
              << "\nExamples:\n"
              << "  " << program_name << " --add-stream=sensor=2,output=./left.h264\n"
              << "  " << program_name << " --add-stream=sensor=2,ipc=/tmp/sensing2.sock\n"
              << "  " << program_name
              << " --add-stream=sensor=2,output=./left.h264 --add-stream=sensor=3,output=./right.h264 "
                 "--mcap-filename=./meta.mcap\n";
}

// =============================================================================
// Main
// =============================================================================

int main(int argc, char** argv)
try
{
    SensingConfig camera_config;
    std::map<uint32_t, StreamConfig> stream_map;
    std::string collection_prefix;
    std::string mcap_filename;

    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];

        if (arg == "--help" || arg == "-h")
        {
            print_usage(argv[0]);
            return 0;
        }
        else if (arg.find("--add-stream=") == 0)
        {
            auto cfg = parse_stream_arg(arg.substr(13));
            stream_map[cfg.sensor_id] = cfg;
        }
        else if (arg.find("--sensor-mode=") == 0)
        {
            camera_config.sensor_mode = static_cast<uint32_t>(std::stoul(arg.substr(14)));
        }
        else if (arg.find("--width=") == 0)
        {
            camera_config.width = static_cast<uint32_t>(std::stoul(arg.substr(8)));
        }
        else if (arg.find("--height=") == 0)
        {
            camera_config.height = static_cast<uint32_t>(std::stoul(arg.substr(9)));
        }
        else if (arg.find("--fps=") == 0)
        {
            camera_config.fps = std::stod(arg.substr(6));
        }
        else if (arg.find("--bitrate=") == 0)
        {
            camera_config.bitrate_bps = static_cast<uint32_t>(std::stoul(arg.substr(10)));
        }
        else if (arg.find("--gop=") == 0)
        {
            camera_config.gop = static_cast<uint32_t>(std::stoul(arg.substr(6)));
        }
        else if (arg.find("--gpu-id=") == 0)
        {
            camera_config.gpu_id = std::stoi(arg.substr(9));
        }
        else if (arg == "--full-range")
        {
            camera_config.full_range = true;
        }
        else if (arg == "--no-swap-uv")
        {
            camera_config.swap_uv = false;
        }
        else if (arg.find("--collection-prefix=") == 0)
        {
            collection_prefix = arg.substr(20);
        }
        else if (arg.find("--mcap-filename=") == 0)
        {
            mcap_filename = arg.substr(16);
        }
        else if (arg.find("--plugin-root-id=") == 0)
        {
            // plugin-root-id is a default argument, so we don't need to store it
        }
        else
        {
            std::cerr << "Unknown option: " << arg << std::endl;
            print_usage(argv[0]);
            return 1;
        }
    }

    if (stream_map.empty())
    {
        std::cerr << "Error: at least one --add-stream is required." << std::endl;
        print_usage(argv[0]);
        return 1;
    }

    std::vector<StreamConfig> stream_configs;
    stream_configs.reserve(stream_map.size());
    for (auto& [_, cfg] : stream_map)
    {
        stream_configs.push_back(std::move(cfg));
    }

    // This process captures and never renders, but EGL is on its critical path:
    // Argus and NvBufSurface both need the Tegra EGL driver, and GLVND hands out
    // Mesa's instead whenever DISPLAY names an X server Tegra EGL cannot drive
    // (Xvfb, or X11 forwarding). libnvbufsurface resolves its own display via
    // eglGetDisplay(EGL_DEFAULT_DISPLAY), so the choice cannot be made per-call
    // -- it has to be gone from the environment before the first EGL call.
    ::unsetenv("DISPLAY");

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    std::cout << "============================================================" << std::endl;
    std::cout << "SENSING Camera Plugin Starting" << std::endl;
    std::cout << "============================================================" << std::endl;

    SensingCamera camera(
        camera_config, stream_configs, create_frame_sink(stream_configs, collection_prefix, mcap_filename));

    std::cout << "------------------------------------------------------------" << std::endl;
    std::cout << "Running capture loop. Press Ctrl+C to stop." << std::endl;

    constexpr auto stats_interval = std::chrono::seconds(5);
    auto last_stats_time = std::chrono::steady_clock::now();

    // ArgusCamera::latest() is a non-blocking mailbox read, so poll at roughly
    // twice the frame rate rather than spinning a core flat out.
    const auto poll_interval =
        std::chrono::microseconds(static_cast<int64_t>(500'000.0 / (camera_config.fps > 0.0 ? camera_config.fps : 30.0)));

    while (!g_stop_requested.load(std::memory_order_relaxed))
    {
        camera.update();

        auto now = std::chrono::steady_clock::now();
        if (now - last_stats_time >= stats_interval)
        {
            camera.print_stats();
            last_stats_time = now;
        }

        std::this_thread::sleep_for(poll_interval);
    }

    std::cout << "------------------------------------------------------------" << std::endl;
    std::cout << "Shutting down SENSING Camera Plugin..." << std::endl;
    camera.flush();
    camera.print_stats();
    std::cout << "Plugin stopped" << std::endl;
    std::cout << "============================================================" << std::endl;

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
