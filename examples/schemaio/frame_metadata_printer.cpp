// SPDX-FileCopyrightText: Copyright (c) 2025-2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @file frame_metadata_printer.cpp
 * @brief Standalone application that reads and prints camera frame metadata from the OpenXR runtime.
 *
 * This application demonstrates using one FrameMetadataTrackerOak per camera stream
 * to read the FrameMetadataOak pushed by a camera plugin.
 *
 * Usage:
 *   ./frame_metadata_printer --collection-prefix=<prefix>
 *
 * The collection-prefix should match the value used by the camera plugin.
 */

#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/frame_metadata_tracker_oak.hpp>
#include <oxr/oxr_session.hpp>
#include <schema/oak_generated.h>

#include <chrono>
#include <iostream>
#include <optional>
#include <string>
#include <thread>
#include <vector>

static constexpr size_t MAX_FLATBUFFER_SIZE = 128;


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

    // One tracker per stream; streams without a pusher simply won't receive data.
    // The plugin publishes each stream as "{collection_prefix}/{StreamName}".
    const std::vector<std::string> stream_names = { "Color", "MonoLeft", "MonoRight" };

    std::cout << "[Step 1] Creating one FrameMetadataTrackerOak per stream..." << std::endl;
    std::vector<std::shared_ptr<core::FrameMetadataTrackerOak>> stream_trackers;
    for (const auto& name : stream_names)
    {
        const std::string collection_id = collection_prefix + "/" + name;
        std::cout << "  " << collection_id << std::endl;
        stream_trackers.push_back(std::make_shared<core::FrameMetadataTrackerOak>(collection_id, MAX_FLATBUFFER_SIZE));
    }

    std::cout << "[Step 2] Creating OpenXR session with required extensions..." << std::endl;
    std::vector<std::shared_ptr<core::ITracker>> trackers(stream_trackers.begin(), stream_trackers.end());
    auto required_extensions = core::DeviceIOSession::get_required_extensions(trackers);
    auto oxr_session = std::make_shared<core::OpenXRSession>("FrameMetadataPrinter", required_extensions);
    std::cout << "  OpenXR session created" << std::endl;

    std::cout << "[Step 3] Creating DeviceIOSession..." << std::endl;
    auto session = core::DeviceIOSession::run(trackers, oxr_session->get_handles());

    std::cout << "[Step 4] Reading samples (press Ctrl+C to stop)..." << std::endl;

    size_t received_count = 0;

    // Per-stream last-seen sequence number. nullopt means the stream has never
    // been observed — the first sample is always printed regardless of its value.
    // If data is already present at startup we seed with its sequence so we don't
    // reprint it; absent data stays nullopt so sequence 0 is never skipped.
    std::vector<std::optional<uint64_t>> last_sequences(stream_trackers.size());
    for (size_t i = 0; i < stream_trackers.size(); ++i)
    {
        const auto& tracked = stream_trackers[i]->get_data(*session);
        if (tracked)
        {
            last_sequences[i] = tracked->sequence_number();
        }
    }

    auto last_status_time = std::chrono::steady_clock::now();
    constexpr auto status_interval = std::chrono::seconds(5);

    while (true)
    {
        session->update();

        // Print one line per stream that has a new sample.
        for (size_t i = 0; i < stream_trackers.size(); ++i)
        {
            const auto& tracked = stream_trackers[i]->get_data(*session);
            if (!tracked || (last_sequences[i].has_value() && tracked->sequence_number() == last_sequences[i].value()))
            {
                continue;
            }
            last_sequences[i] = tracked->sequence_number();
            std::cout << "Sample " << ++received_count << ": " << core::EnumNameStreamType(tracked->stream())
                      << " seq=" << tracked->sequence_number() << std::endl;
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
