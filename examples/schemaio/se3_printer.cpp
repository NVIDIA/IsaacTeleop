// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @file se3_printer.cpp
 * @brief Standalone application that reads and prints SE3 tracker poses from the OpenXR runtime.
 *
 * This application demonstrates using Se3Tracker to read Se3TrackerPose FlatBuffer samples
 * pushed by an SE3 producer plugin (e.g. controller_se3_tracker). The application creates
 * the OpenXR session with required extensions and uses DeviceIOSession to manage the tracker.
 *
 * Note: Both pusher and reader agree on the schema (Se3TrackerPose from se3_tracker.fbs), so the
 * schema does not need to be sent over the wire. The collection ID must match the producer's;
 * pass it as the first argument to read a non-default stream (multiple SE3 trackers stream on
 * distinct collection IDs).
 */

#include "common_utils.hpp"

#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/se3_tracker.hpp>
#include <oxr/oxr_session.hpp>

#include <chrono>
#include <iomanip>
#include <iostream>
#include <string>
#include <thread>
#include <vector>

using namespace schemaio_example;

void print_se3_data(const core::Se3TrackerPoseT& data, size_t sample_count)
{
    std::cout << "Sample " << sample_count;

    if (!data.is_valid)
    {
        // Pose contents are unspecified while tracking is lost (see se3_tracker.fbs) —
        // gate on is_valid, never on pose values.
        std::cout << " [tracking lost]" << std::endl;
        return;
    }

    const auto& position = data.pose->position();
    const auto& orientation = data.pose->orientation();
    std::cout << std::fixed << std::setprecision(3) << " pos=[" << position.x() << ", " << position.y() << ", "
              << position.z() << "] quat(xyzw)=[" << orientation.x() << ", " << orientation.y() << ", "
              << orientation.z() << ", " << orientation.w() << "]";

    std::cout << std::endl;
}

int main(int argc, char** argv)
try
{
    const std::string collection_id = (argc > 1) ? argv[1] : std::string(core::Se3Tracker::TENSOR_IDENTIFIER);

    std::cout << "SE3 Printer (collection: " << collection_id << ")" << std::endl;

    // Step 1: Create the tracker
    std::cout << "[Step 1] Creating Se3Tracker..." << std::endl;
    auto tracker = std::make_shared<core::Se3Tracker>(collection_id);

    // Step 2: Get required extensions and create OpenXR session
    std::cout << "[Step 2] Creating OpenXR session with required extensions..." << std::endl;

    std::vector<std::shared_ptr<core::ITracker>> trackers = { tracker };
    auto required_extensions = core::DeviceIOSession::get_required_extensions(trackers);

    auto oxr_session = std::make_shared<core::OpenXRSession>("Se3Printer", required_extensions);

    std::cout << "  OpenXR session created" << std::endl;

    // Step 3: Create DeviceIOSession with the tracker
    std::cout << "[Step 3] Creating DeviceIOSession..." << std::endl;

    std::unique_ptr<core::DeviceIOSession> session;
    session = core::DeviceIOSession::run(trackers, oxr_session->get_handles());

    // Step 4: Read samples by updating the session
    std::cout << "[Step 4] Reading samples..." << std::endl;

    size_t received_count = 0;
    while (received_count < MAX_SAMPLES)
    {
        // Update session (this calls update on all trackers). Each update drains ALL
        // samples pending in the tensor collection, so the first tick consumes any
        // backlog and get_data() below always exposes the latest pose.
        session->update();

        // Print current data if available. Note: the live backend retains the
        // last-known sample between pushes, so without the fixed-rate sleep below this
        // loop would spin and reprint stale data as fast as the CPU allows.
        const auto& tracked = tracker->get_data(*session);
        if (tracked.data)
        {
            print_se3_data(*tracked.data, received_count++);
        }

        // Tick at ~90 Hz to match the controller_se3_tracker plugin's push rate.
        std::this_thread::sleep_for(std::chrono::milliseconds(33));
    }

    std::cout << "\nDone. Received " << received_count << " samples." << std::endl;
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
