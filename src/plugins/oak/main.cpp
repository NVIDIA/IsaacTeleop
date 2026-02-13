// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include "core/frame_sink.hpp"
#include "core/oak_camera.hpp"

#include <atomic>
#include <chrono>
#include <csignal>
#include <iostream>
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
// Usage
// =============================================================================

void print_usage(const char* program_name)
{
    std::cout << "Usage: " << program_name << " [options]\n"
              << "\nCamera Settings:\n"
              << "  --width=N           Frame width (default: 1920)\n"
              << "  --height=N          Frame height (default: 1080)\n"
              << "  --fps=N             Frame rate (default: 30)\n"
              << "  --bitrate=N         H.264 bitrate in bps (default: 8000000)\n"
              << "  --quality=N         H.264 quality 1-100 (default: 80)\n"
              << "\nRecording Settings:\n"
              << "  --output=PATH       Full path for recording file (required)\n"
              << "\nOpenXR Settings:\n"
              << "  --collection-id=ID  Tensor collection ID for metadata (default: oak_camera)\n"
              << "\nGeneral Settings:\n"
              << "  --help              Show this help message\n"
              << "\nOutput:\n"
              << "  Records raw H.264 NAL units to file.\n";
}

// =============================================================================
// Main
// =============================================================================

int main(int argc, char** argv)
try
{
    // Default configurations
    OakConfig camera_config;
    std::string output_path;
    std::string plugin_root_id = "oak_camera";
    std::string collection_id;

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
        else if (arg.find("--output=") == 0)
        {
            output_path = arg.substr(9);
        }
        else if (arg.find("--collection-id=") == 0)
        {
            collection_id = arg.substr(16);
        }
        else if (arg.find("--plugin-root-id=") == 0)
        {
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

    std::cout << "============================================================" << std::endl;
    std::cout << "OAK Camera Plugin Starting" << std::endl;
    std::cout << "============================================================" << std::endl;

    if (output_path.empty())
    {
        std::cerr << "Error: --output=PATH is required." << std::endl;
        print_usage(argv[0]);
        return 1;
    }

    // Create camera and frame sink (H.264 writer + metadata pusher)
    OakCamera camera(camera_config);
    FrameSink sink(output_path, collection_id);

    uint64_t frame_count = 0;
    auto start_time = std::chrono::steady_clock::now();

    std::cout << "------------------------------------------------------------" << std::endl;
    std::cout << "Running capture loop. Press Ctrl+C to stop." << std::endl;

    constexpr auto status_interval = std::chrono::seconds(10);
    auto last_status_time = std::chrono::steady_clock::now();

    // Main capture loop
    while (!g_stop_requested.load(std::memory_order_relaxed))
    {
        auto frame = camera.get_frame();
        if (frame)
        {
            sink.on_frame(*frame);
            frame_count++;
        }

        // Periodic status update
        auto now = std::chrono::steady_clock::now();
        if (now - last_status_time >= status_interval)
        {
            std::cout << "Frames: " << frame_count << std::endl;
            last_status_time = now;
        }
    }

    // Print statistics
    std::cout << "------------------------------------------------------------" << std::endl;
    std::cout << "Shutting down OAK Camera Plugin..." << std::endl;

    auto duration = std::chrono::steady_clock::now() - start_time;
    auto seconds = std::chrono::duration_cast<std::chrono::seconds>(duration).count();
    double fps = seconds > 0 ? static_cast<double>(frame_count) / seconds : 0.0;

    std::cout << "Session stats: " << frame_count << " frames in " << seconds << "s (" << std::fixed
              << std::setprecision(1) << fps << " fps)" << std::endl;
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
