// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @file pedal_printer.cpp
 * @brief Standalone application that reads and prints foot pedal data from the OpenXR runtime.
 *
 * This application demonstrates using Generic3AxisPedalTracker to read Generic3AxisPedalOutput
 * FlatBuffer samples pushed by pedal_pusher. The application creates the OpenXR
 * session with required extensions and uses DeviceIOSession to manage the tracker.
 *
 * Note: Both pusher and reader agree on the schema (Generic3AxisPedalOutput from pedals.fbs), so the schema
 * does not need to be sent over the wire.
 */

#include "common_utils.hpp"

#include <deviceio/deviceio_session.hpp>
#include <deviceio/generic_3axis_pedal_tracker.hpp>
#include <oxr/oxr_session.hpp>

#include <chrono>
#include <iomanip>
#include <iostream>
#include <thread>
#include <vector>

using namespace schemaio_example;

void print_pedal_data(const core::Generic3AxisPedalOutputT& data, size_t sample_count)
{
    std::cout << "Sample " << sample_count;

    std::cout << std::fixed << std::setprecision(3) << " [is_active=" << (data.is_active ? "true" : "false")
              << ", left=" << data.left_pedal << ", right=" << data.right_pedal << ", rudder=" << data.rudder << "]";

    std::cout << std::endl;
}

int main(int argc, char** argv)
try
{
    std::cout << "Pedal Printer (collection: " << COLLECTION_ID << ")" << std::endl;

    // Step 1: Create the tracker
    std::cout << "[Step 1] Creating Generic3AxisPedalTracker..." << std::endl;
    auto tracker = std::make_shared<core::Generic3AxisPedalTracker>(COLLECTION_ID, MAX_FLATBUFFER_SIZE);

    // Step 2: Get required extensions and create OpenXR session
    std::cout << "[Step 2] Creating OpenXR session with required extensions..." << std::endl;

    std::vector<std::shared_ptr<core::ITracker>> trackers = { tracker };
    auto required_extensions = core::DeviceIOSession::get_required_extensions(trackers);

    auto oxr_session = std::make_shared<core::OpenXRSession>("PedalPrinter", required_extensions);

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
        // Update session (this calls update on all trackers)
        if (!session->update())
        {
            std::cerr << "Update failed" << std::endl;
            break;
        }

        // Print current data if available
        const auto& data = tracker->get_data(*session);
        if (data.is_active)
        {
            print_pedal_data(data, received_count++);
        }
        else
        {
            // Sleep to approximately match the push rate (50ms)
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
        }
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
