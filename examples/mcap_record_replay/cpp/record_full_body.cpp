// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @file record_full_body.cpp
 * @brief Record a live full-body tracking session to an MCAP file using only the C++ API.
 *
 * C++ counterpart of record_full_body.py. Creates a FullBodyTracker, opens an OpenXR
 * session with its required extensions, and passes a McapRecordingConfig to
 * DeviceIOSession::run() — the tracker impl then writes MCAP samples during each
 * session->update() call. Unlike the Python example this does not launch the CloudXR runtime;
 * start it (and connect the headset) before running — or launch the runtime, printer, and
 * recorder together with python -m isaacteleop.rig rigs/full_body.yaml.
 *
 * Usage:
 *     record_full_body [duration_seconds] [output.mcap]
 *
 * Defaults: 5 seconds -> full_body_<timestamp>.mcap in the current directory.
 *
 * The recording uses the same "full_body" channel base name as FullBodySource in the Python
 * examples, so the file replays unchanged with
 * examples/mcap_record_replay/python/replay_full_body.py.
 */

#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/full_body_tracker.hpp>
#include <oxr/oxr_session.hpp>
#include <schema/full_body_generated.h>

#include <chrono>
#include <cstdint>
#include <ctime>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <string>
#include <thread>
#include <vector>

namespace
{

// Channel base name matching FullBodySource(name="full_body") in the Python examples. MCAP
// topics become "<base_name>/<sub_channel>", so this must be "full_body" for the recording to
// be readable by replay_full_body.py.
constexpr const char* MCAP_BASE_NAME = "full_body";

std::string default_output_path()
{
    const std::time_t now = std::chrono::system_clock::to_time_t(std::chrono::system_clock::now());
    std::tm tm_buf{};
    localtime_r(&now, &tm_buf);
    std::ostringstream name;
    name << "full_body_" << std::put_time(&tm_buf, "%Y%m%d_%H%M%S") << ".mcap";
    return name.str();
}

uint32_t count_valid_joints(const core::FullBodyPoseT& data)
{
    uint32_t valid_count = 0;
    for (uint32_t i = 0; i < core::FullBodyTracker::JOINT_COUNT; ++i)
    {
        if ((*data.joints->joints())[i]->is_valid())
        {
            ++valid_count;
        }
    }
    return valid_count;
}

} // namespace

int main(int argc, char** argv)
try
{
    const double duration_s = (argc > 1) ? std::stod(argv[1]) : 5.0;
    const std::string mcap_path = (argc > 2) ? argv[2] : default_output_path();

    std::cout << "[record] writing " << mcap_path << " for " << duration_s << "s" << std::endl;

    // Step 1: Create the tracker
    auto tracker = std::make_shared<core::FullBodyTracker>();

    // Step 2: Get required extensions and create OpenXR session
    std::vector<std::shared_ptr<core::ITracker>> trackers = { tracker };
    auto required_extensions = core::DeviceIOSession::get_required_extensions(trackers);

    auto oxr_session = std::make_shared<core::OpenXRSession>("McapFullBodyRecordExample", required_extensions);

    // Step 3: Create DeviceIOSession with recording enabled
    core::McapRecordingConfig recording_config{ mcap_path, { { tracker.get(), MCAP_BASE_NAME } } };

    auto session = core::DeviceIOSession::run(trackers, oxr_session->get_handles(), std::move(recording_config));

    // Step 4: Update the session for the requested duration. The tracker impl writes the MCAP
    // sample during each update(); no explicit write call is needed here.
    const auto start = std::chrono::steady_clock::now();
    size_t frame_count = 0;
    while (true)
    {
        const double elapsed_s = std::chrono::duration<double>(std::chrono::steady_clock::now() - start).count();
        if (elapsed_s >= duration_s)
        {
            break;
        }

        session->update();

        if (frame_count % 60 == 0)
        {
            const auto& tracked = tracker->get_body_pose(*session);
            std::cout << "[record] t=" << std::fixed << std::setprecision(2) << elapsed_s << "s  frame=" << frame_count;
            if (tracked.data)
            {
                std::cout << "  joints=" << count_valid_joints(*tracked.data) << "/"
                          << core::FullBodyTracker::JOINT_COUNT;
            }
            else
            {
                std::cout << "  [body tracking inactive]";
            }
            std::cout << std::endl;
        }
        ++frame_count;

        // Tick at ~60 Hz, matching record_full_body.py.
        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }

    // Destroying the session closes the MCAP writer and emits the summary/statistics block that
    // replay tooling (e.g. replay_full_body.py) relies on — exit normally rather than aborting.
    session.reset();

    std::cout << "[record] done — " << mcap_path << std::endl;
    std::cout << "[record] replay with: python examples/mcap_record_replay/python/replay_full_body.py " << mcap_path
              << std::endl;
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
