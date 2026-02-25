// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @file frame_metadata_printer.cpp
 * @brief Standalone application that reads and prints camera frame metadata from the OpenXR runtime.
 *
 * This application demonstrates using FrameMetadataTrackerOak to read per-stream
 * FrameMetadataOak pushed by a camera plugin, with each stream on its own MCAP channel.
 *
 * Usage:
 *   ./frame_metadata_printer --collection-prefix=<prefix>
 *
 * The collection-prefix should match the value used by the camera plugin.
 */

#include <deviceio/deviceio_session.hpp>
#include <deviceio/frame_metadata_tracker_oak.hpp>
#include <oxr/oxr_session.hpp>

#include <chrono>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

static constexpr size_t MAX_FLATBUFFER_SIZE = 128;

void print_oak_metadata(const core::FrameMetadataTrackerOak& tracker,
                        const core::DeviceIOSession& session,
                        size_t sample_count)
{
    std::cout << "Sample " << sample_count << ": ";
    for (size_t i = 0; i < tracker.get_stream_count(); ++i)
    {
        const auto& md = tracker.get_stream_data(session, i);
        if (i > 0)
            std::cout << " | ";
        std::cout << core::EnumNameStreamType(md.stream) << " seq=" << md.sequence_number;
        if (md.timestamp)
            std::cout << " dt=" << md.timestamp->device_time();
    }
    std::cout << std::endl;
}

void print_usage(const char* program_name)
{
    std::cout << "Usage: " << program_name << " [options]\n"
              << "\nOptions:\n"
              << "  --collection-prefix=PREFIX  Tensor collection prefix (default: oak_camera)\n"
              << "  --help                      Show this help message\n"
              << "\nDescription:\n"
              << "  Reads and prints per-stream FrameMetadataOak samples pushed by a camera plugin.\n"
              << "  The collection-prefix must match the value used by the camera plugin.\n";
}

int main(int argc, char** argv)
try
{
    std::string collection_prefix = "oak_camera";

    for (int i = 1; i < argc; ++i)
    {
        std::string arg = argv[i];

        if (arg == "--help" || arg == "-h")
        {
            print_usage(argv[0]);
            return 0;
        }
        else if (arg.find("--collection-prefix=") == 0)
        {
            collection_prefix = arg.substr(20);
        }
        else
        {
            std::cerr << "Unknown option: " << arg << std::endl;
            print_usage(argv[0]);
            return 1;
        }
    }

    std::cout << "Frame Metadata Printer (prefix: " << collection_prefix << ")" << std::endl;

    // Track all three stream types; streams without a pusher simply won't receive data.
    std::vector<core::StreamType> streams = { core::StreamType_Color, core::StreamType_MonoLeft,
                                              core::StreamType_MonoRight };

    std::cout << "[Step 1] Creating FrameMetadataTrackerOak..." << std::endl;
    auto tracker = std::make_shared<core::FrameMetadataTrackerOak>(collection_prefix, streams, MAX_FLATBUFFER_SIZE);

    std::cout << "[Step 2] Creating OpenXR session with required extensions..." << std::endl;
    std::vector<std::shared_ptr<core::ITracker>> trackers = { tracker };
    auto required_extensions = core::DeviceIOSession::get_required_extensions(trackers);
    auto oxr_session = std::make_shared<core::OpenXRSession>("FrameMetadataPrinter", required_extensions);
    std::cout << "  OpenXR session created" << std::endl;

    std::cout << "[Step 3] Creating DeviceIOSession..." << std::endl;
    auto session = core::DeviceIOSession::run(trackers, oxr_session->get_handles());

    std::cout << "[Step 4] Reading samples (press Ctrl+C to stop)..." << std::endl;

    size_t received_count = 0;
    int64_t last_device_time = -1;
    auto last_status_time = std::chrono::steady_clock::now();
    constexpr auto status_interval = std::chrono::seconds(5);

    while (true)
    {
        if (!session->update())
        {
            std::cerr << "Update failed" << std::endl;
            break;
        }

        // Detect new data by checking if any stream has a newer device_time
        int64_t max_dt = -1;
        for (size_t i = 0; i < tracker->get_stream_count(); ++i)
        {
            const auto& md = tracker->get_stream_data(*session, i);
            if (md.timestamp)
                max_dt = std::max(max_dt, md.timestamp->device_time());
        }
        if (max_dt > last_device_time)
        {
            print_oak_metadata(*tracker, *session, ++received_count);
            last_device_time = max_dt;
        }

        auto now = std::chrono::steady_clock::now();
        if (received_count == 0 && now - last_status_time >= status_interval)
        {
            std::cout << "Waiting for data from prefix: " << collection_prefix << "..." << std::endl;
            last_status_time = now;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(10));
    }

    std::cout << "\nTotal samples received: " << received_count << std::endl;
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
