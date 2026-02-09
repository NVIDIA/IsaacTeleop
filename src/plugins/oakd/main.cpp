// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "oakd_camera.hpp"

#include <camera_core/camera_plugin.hpp>

#include <csignal>
#include <iostream>
#include <string>

using namespace core;

// Global plugin pointer for signal handler
CameraPlugin* g_plugin = nullptr;

void signal_handler(int signal)
{
    if (signal == SIGINT || signal == SIGTERM)
    {
        if (g_plugin)
        {
            g_plugin->request_stop();
        }
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
              << "  --record=PATH       Output file path (.h264)\n"
              << "  --record-dir=DIR    Directory for auto-named recordings (default: ./recordings)\n"
              << "\nOpenXR Settings:\n"
              << "  --plugin-root-id=ID Tensor collection ID for metadata (default: oakd_camera)\n"
              << "\nGeneral Settings:\n"
              << "  --help              Show this help message\n"
              << "\nOutput:\n"
              << "  Records raw H.264 NAL units to file.\n";
}

int main(int argc, char** argv)
try
{
    // Default configurations
    CameraConfig camera_config;
    RecordConfig record_config;
    std::string plugin_root_id = "oakd_camera";

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
        }
        else if (arg.find("--height=") == 0)
        {
            camera_config.height = std::stoi(arg.substr(9));
        }
        else if (arg.find("--fps=") == 0)
        {
            camera_config.fps = std::stoi(arg.substr(6));
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
        }
        else if (arg.find("--record-dir=") == 0)
        {
            record_config.output_dir = arg.substr(13);
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

    std::cout << "Camera Plugin (OAK-D)" << std::endl;

    // Create and run plugin
    auto camera = std::make_unique<plugins::oakd::OakDCamera>(camera_config);
    CameraPlugin plugin(std::move(camera), record_config, plugin_root_id);
    g_plugin = &plugin;

    std::cout << "Plugin running. Press Ctrl+C to stop." << std::endl;
    plugin.capture_loop();

    g_plugin = nullptr;

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
