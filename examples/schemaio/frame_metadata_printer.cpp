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
    const std::vector<std::string> collection_ids = {
        collection_prefix + "/Color",
        collection_prefix + "/MonoLeft",
        collection_prefix + "/MonoRight",
    };

    std::cout << "[Step 1] Creating FrameMetadataTrackerOak instances..." << std::endl;
    std::vector<std::shared_ptr<core::FrameMetadataTrackerOak>> trackers;
    trackers.reserve(collection_ids.size());
    for (const auto& cid : collection_ids)
        trackers.push_back(std::make_shared<core::FrameMetadataTrackerOak>(cid, MAX_FLATBUFFER_SIZE));

    std::cout << "[Step 2] Creating OpenXR session with required extensions..." << std::endl;
    std::vector<std::shared_ptr<core::ITracker>> itracker_list(trackers.begin(), trackers.end());
    auto required_extensions = core::DeviceIOSession::get_required_extensions(itracker_list);
    auto oxr_session = std::make_shared<core::OpenXRSession>("FrameMetadataPrinter", required_extensions);
    std::cout << "  OpenXR session created" << std::endl;

    std::cout << "[Step 3] Creating DeviceIOSession..." << std::endl;
    auto session = core::DeviceIOSession::run(itracker_list, oxr_session->get_handles());

    std::cout << "[Step 4] Reading samples (press Ctrl+C to stop)..." << std::endl;

    size_t received_count = 0;

    // Per-tracker last-seen sequence number. nullopt means the stream has never
    // been observed — the first sample is always printed regardless of its value.
    std::vector<std::optional<uint64_t>> last_sequences(trackers.size());
    for (size_t i = 0; i < trackers.size(); ++i)
    {
        const auto& tracked = trackers[i]->get_data(*session);
        if (tracked.data)
            last_sequences[i] = tracked.data->sequence_number;
    }

    auto last_status_time = std::chrono::steady_clock::now();
    constexpr auto status_interval = std::chrono::seconds(5);

    while (true)
    {
        session->update();

        for (size_t i = 0; i < trackers.size(); ++i)
        {
            const auto& tracked = trackers[i]->get_data(*session);
            if (!tracked.data ||
                (last_sequences[i].has_value() && tracked.data->sequence_number == last_sequences[i].value()))
            {
                continue;
            }
            last_sequences[i] = tracked.data->sequence_number;
            std::cout << "Sample " << ++received_count << ": " << core::EnumNameStreamType(tracked.data->stream)
                      << " seq=" << tracked.data->sequence_number << std::endl;
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
