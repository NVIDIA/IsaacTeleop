// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "core/frame_sink.hpp"
#include "core/oak_camera.hpp"
#include "core/preview_stream.hpp"

#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
#include <map>
#include <sstream>
#include <string>

using namespace plugins::oak;

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

static core::StreamType parse_camera_name(const std::string& name)
{
    if (name == "Color")
        return core::StreamType_Color;
    if (name == "MonoLeft")
        return core::StreamType_MonoLeft;
    if (name == "MonoRight")
        return core::StreamType_MonoRight;

    throw std::runtime_error("Unknown camera name: '" + name + "'. Expected Color, MonoLeft, or MonoRight.");
}

static StreamConfig parse_stream_arg(const std::string& arg)
{
    StreamConfig cfg{};
    bool has_camera = false;
    bool has_output = false;

    std::istringstream ss(arg);
    std::string token;
    while (std::getline(ss, token, ','))
    {
        auto eq = token.find('=');
        if (eq == std::string::npos)
            throw std::runtime_error("Invalid key=value in --add-stream: '" + token + "'");

        auto key = token.substr(0, eq);
        auto val = token.substr(eq + 1);

        if (key == "camera")
        {
            cfg.camera = parse_camera_name(val);
            has_camera = true;
        }
        else if (key == "output")
        {
            cfg.output_path = val;
            has_output = true;
        }
        else
        {
            throw std::runtime_error("Unknown key in --add-stream: '" + key + "'");
        }
    }

    if (!has_camera)
        throw std::runtime_error("--add-stream requires camera=<name>");
    if (!has_output)
        throw std::runtime_error("--add-stream requires output=<path>");

    return cfg;
}

// =============================================================================
// Usage
// =============================================================================

void print_usage(const char* program_name)
{
    std::cout
        << "Usage: " << program_name << " [options] --add-stream ...\n"
        << "\nStream Configuration (repeatable):\n"
        << "  --add-stream camera=<name>,output=<path>\n"
        << "      camera: Color, MonoLeft, or MonoRight\n"
        << "      output: file path for this stream's H.264 data\n"
        << "\nGlobal Camera Settings:\n"
        << "  --fps=N             Frame rate for all streams (default: 30)\n"
        << "  --bitrate=N         H.264 bitrate in bps (default: 8000000)\n"
        << "  --quality=N         H.264 quality 1-100 (default: 80)\n"
        << "  --device-id=ID      OAK device MxId (default: first available)\n"
        << "\nMetadata (mutually exclusive):\n"
        << "  --collection-prefix=PREFIX  Push metadata via OpenXR tensor extensions\n"
        << "  --mcap-filename=PATH        Record metadata to an MCAP file\n"
        << "\nPreview:\n"
        << "  --preview           Show live color camera preview via OpenCV window\n"
        << "\nGeneral:\n"
        << "  --help              Show this help message\n"
        << "\nExamples:\n"
        << "  " << program_name << " --add-stream camera=Color,output=./color.h264\n"
        << "  " << program_name
        << " --add-stream=camera=Color,output=./color.h264 --add-stream=camera=LeftMono,output=./left.h264 --add-stream=camera=RightMono,output=./right.h264\n";
}

// =============================================================================
// Main
// =============================================================================

int main(int argc, char** argv)
try
{
    OakConfig camera_config;
    std::map<core::StreamType, StreamConfig> stream_map;
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
            stream_map[cfg.camera] = cfg;
        }
        else if (arg.find("--fps=") == 0)
        {
            camera_config.fps = std::stof(arg.substr(6));
        }
        else if (arg.find("--bitrate=") == 0)
        {
            camera_config.bitrate = std::stoi(arg.substr(10));
        }
        else if (arg.find("--quality=") == 0)
        {
            camera_config.quality = std::stoi(arg.substr(10));
        }
        else if (arg.find("--device-id=") == 0)
        {
            camera_config.device_id = arg.substr(12);
        }
        else if (arg == "--preview")
        {
            camera_config.preview = true;
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

    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    std::cout << "============================================================" << std::endl;
    std::cout << "OAK Camera Plugin Starting" << std::endl;
    std::cout << "============================================================" << std::endl;

    OakCamera camera(camera_config, stream_configs, create_frame_sink(stream_configs, collection_prefix, mcap_filename));

    std::cout << "------------------------------------------------------------" << std::endl;
    std::cout << "Running capture loop. Press Ctrl+C to stop." << std::endl;

    constexpr auto stats_interval = std::chrono::seconds(5);
    auto last_stats_time = std::chrono::steady_clock::now();

    while (!g_stop_requested.load(std::memory_order_relaxed))
    {
        camera.update();

        auto now = std::chrono::steady_clock::now();
        if (now - last_stats_time >= stats_interval)
        {
            camera.print_stats();
            last_stats_time = now;
        }
    }

    std::cout << "------------------------------------------------------------" << std::endl;
    std::cout << "Shutting down OAK Camera Plugin..." << std::endl;
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
