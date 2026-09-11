// SPDX-FileCopyrightText: Copyright (c) 2026 j-mex. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @file jmex_joint_state_printer.cpp
 * @brief Reads what jmex_plugin publishes and prints it, with no Python and no retargeting graph.
 *
 * Confirms plugin output reaches JointStateTracker through OpenXR. Usage:
 * ``jmex_joint_state_printer [collection_id]`` (default: "jmex").
 */

#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/joint_state_tracker.hpp>
#include <jmex/joint_state_publisher.hpp>
#include <oxr/oxr_session.hpp>

#include <chrono>
#include <iomanip>
#include <iostream>
#include <memory>
#include <string>
#include <thread>
#include <vector>

int main(int argc, char** argv)
try
{
    const std::string collection_id = (argc > 1) ? argv[1] : "jmex";

    std::cout << "jmex joint state printer (collection: " << collection_id << ")" << std::endl;

    auto tracker = std::make_shared<core::JointStateTracker>(
        collection_id, plugins::jmex::JointStatePublisher::MAX_FLATBUFFER_SIZE);

    std::vector<std::shared_ptr<core::ITracker>> trackers = { tracker };
    auto oxr_session = std::make_shared<core::OpenXRSession>(
        "JmexJointStatePrinter", core::DeviceIOSession::get_required_extensions(trackers));
    auto session = core::DeviceIOSession::run(trackers, oxr_session->get_handles());

    size_t sample = 0;
    while (true)
    {
        session->update();

        const auto& tracked = tracker->get_data(*session);
        if (!tracked.data)
        {
            // No sample: the plugin is not running, or MOXI Player has not paired yet.
            std::this_thread::sleep_for(std::chrono::milliseconds(50));
            continue;
        }

        const auto& data = *tracked.data;
        std::cout << "Sample " << sample++ << " [device=" << data.device_id << ", joints=" << data.joints.size() << "]"
                  << std::fixed << std::setprecision(3) << std::endl;
        for (const auto& joint : data.joints)
        {
            std::cout << "    " << std::setw(32) << std::left << joint->name << " " << std::setw(8) << std::right
                      << joint->position << " rad";
            if (data.has_velocity)
            {
                std::cout << "  " << std::setw(8) << joint->velocity << " rad/s";
            }
            std::cout << std::endl;
        }

        // One dump per second is enough to read; the point is that data arrives, not its rate.
        std::this_thread::sleep_for(std::chrono::seconds(1));
    }

    return 0;
}
catch (const std::exception& e)
{
    std::cerr << argv[0] << ": " << e.what() << std::endl;
    return 1;
}
catch (...)
{
    std::cerr << argv[0] << ": Unknown error" << std::endl;
    return 1;
}
