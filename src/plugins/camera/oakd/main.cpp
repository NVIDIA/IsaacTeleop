// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <core/camera_plugin.hpp>

#include <atomic>
#include <csignal>
#include <cstring>
#include <iostream>
#include <memory>
#include <oakd_camera.hpp>
#include <string>

using namespace plugins::camera;

// Signal-safe atomic for stop request
static_assert(ATOMIC_BOOL_LOCK_FREE, "lock-free atomic bool is required for signal safety");
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
              << "\nCamera Settings:\n"
              << "  --width=N           Frame width (default: 1280)\n"
              << "  --height=N          Frame height (default: 720)\n"
              << "  --fps=N             Frame rate (default: 30)\n"
              << "  --bitrate=N         H.264 bitrate in bps (default: 8000000)\n"
              << "  --quality=N         H.264 quality 1-100 (default: 80)\n"
              << "\nRecording Settings:\n"
              << "  --record=PATH       Output file path (.mp4)\n"
              << "  --record-dir=DIR    Directory for auto-named recordings (default: ./recordings)\n"
              << "\nGeneral Settings:\n"
              << "  --retry-interval=N  Camera init retry interval in seconds (default: 5)\n"
              << "  --plugin-root-id=ID Plugin root ID for TeleopCore (default: oakd_camera)\n"
              << "  --help              Show this help message\n"
              << "\nOutput:\n"
              << "  Records directly to MP4 using FFmpeg.\n";
}

int main(int argc, char** argv)
{
    // Default configurations
    CameraConfig camera_config;
    RecordConfig record_config;
    std::string plugin_root_id = "oakd_camera";
    int retry_interval = 5;

    // Parse command line arguments
    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];

        if (arg == "--help" || arg == "-h")
        {
            print_usage(argv[0]);
            return 0;
        }
        else if (arg.find("--width=") == 0)
        {
            camera_config.width = std::stoi(arg.substr(8));
            record_config.width = camera_config.width;
        }
        else if (arg.find("--height=") == 0)
        {
            camera_config.height = std::stoi(arg.substr(9));
            record_config.height = camera_config.height;
        }
        else if (arg.find("--fps=") == 0)
        {
            camera_config.fps = std::stoi(arg.substr(6));
            record_config.fps = camera_config.fps;
        }
        else if (arg.find("--bitrate=") == 0)
        {
            camera_config.bitrate = std::stoi(arg.substr(10));
        }
        else if (arg.find("--quality=") == 0)
        {
            camera_config.quality = std::stoi(arg.substr(10));
        }
        else if (arg.find("--record=") == 0)
        {
            record_config.output_path = arg.substr(9);
            record_config.auto_name = false;
        }
        else if (arg.find("--record-dir=") == 0)
        {
            record_config.output_dir = arg.substr(13);
        }
        else if (arg.find("--retry-interval=") == 0)
        {
            retry_interval = std::stoi(arg.substr(17));
        }
        else if (arg.find("--plugin-root-id=") == 0)
        {
            plugin_root_id = arg.substr(17);
        }
        else
        {
            std::cerr << "Unknown option: " << arg << std::endl;
            print_usage(argv[0]);
            return 1;
        }
    }

    // Setup signal handlers
    std::signal(SIGINT, signal_handler);
    std::signal(SIGTERM, signal_handler);

    std::cout << "Camera Plugin (OAK-D) v1.0.0" << std::endl;
    std::cout << "Plugin Root ID: " << plugin_root_id << std::endl;

    // OAK-D camera factory
    auto oakd_factory = [](const CameraConfig& config) -> std::unique_ptr<ICamera>
    { return std::make_unique<oakd::OakDCamera>(config); };

    // Create and run plugin
    std::unique_ptr<CameraPlugin> plugin;
    try
    {
        plugin =
            std::make_unique<CameraPlugin>(oakd_factory, camera_config, record_config, plugin_root_id, retry_interval);
    }
    catch (const std::exception& e)
    {
        std::cerr << "Failed to create plugin: " << e.what() << std::endl;
        return 1;
    }

    std::cout << "Plugin running. Press Ctrl+C to stop." << std::endl;

    // Wait for stop signal
    while (!g_stop_requested.load(std::memory_order_relaxed) && !plugin->stop_requested())
    {
        std::this_thread::sleep_for(std::chrono::milliseconds(100));
    }

    // Request plugin stop
    plugin->request_stop();

    // Plugin destructor handles cleanup
    plugin.reset();

    return 0;
}
