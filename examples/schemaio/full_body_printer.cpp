// SPDX-FileCopyrightText: Copyright (c) 2026 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

/*!
 * @file full_body_printer.cpp
 * @brief Standalone application that reads and prints PICO full-body poses from the OpenXR runtime.
 *
 * This application demonstrates using FullBodyTracker (XR_BD_body_tracking) to read the
 * 24-joint body skeleton through DeviceIOSession. Requires a runtime with body tracking support
 * (e.g. CloudXR streaming from a PICO 4 Ultra Enterprise with Motion Trackers); when the system
 * does not support body tracking the tracker runs in limp mode and no samples are printed.
 * The full_body rig (rigs/full_body.yaml) launches this printer together with the CloudXR
 * runtime and the MCAP recorder in one tmux session.
 *
 * To record a full-body session to MCAP from C++, see
 * examples/mcap_record_replay/cpp/record_full_body.cpp.
 */

#include "common_utils.hpp"

#include <deviceio_session/deviceio_session.hpp>
#include <deviceio_trackers/full_body_tracker.hpp>
#include <oxr/oxr_session.hpp>
#include <schema/full_body_generated.h>

#include <chrono>
#include <cstdint>
#include <iomanip>
#include <iostream>
#include <memory>
#include <thread>
#include <vector>

using namespace schemaio_example;

namespace
{

// Joint poses are unspecified while their tracking is lost — gate on is_valid per joint
// (all_joint_poses_tracked is a whole-skeleton quality flag only).
void print_joint(const char* label, const core::BodyJointPose& joint)
{
    if (joint.is_valid())
    {
        const auto& position = joint.pose().position();
        std::cout << " " << label << "=[" << position.x() << ", " << position.y() << ", " << position.z() << "]";
    }
    else
    {
        std::cout << " " << label << "=[not tracked]";
    }
}

void print_body_pose(const core::FullBodyPoseT& data, size_t sample_count)
{
    const auto& joints = *data.joints->joints();

    uint32_t valid_count = 0;
    for (uint32_t i = 0; i < core::FullBodyTracker::JOINT_COUNT; ++i)
    {
        if (joints[i]->is_valid())
        {
            ++valid_count;
        }
    }

    std::cout << "Sample " << sample_count << std::fixed << std::setprecision(3) << " valid=" << valid_count << "/"
              << core::FullBodyTracker::JOINT_COUNT;
    print_joint("pelvis", *joints[core::BodyJoint_PELVIS]);
    print_joint("head", *joints[core::BodyJoint_HEAD]);
    std::cout << std::endl;
}

} // namespace

int main(int argc, char** argv)
try
{
    std::cout << "Full Body Printer (XR_BD_body_tracking)" << std::endl;

    // Step 1: Create the tracker
    std::cout << "[Step 1] Creating FullBodyTracker..." << std::endl;
    auto tracker = std::make_shared<core::FullBodyTracker>();

    // Step 2: Get required extensions and create OpenXR session
    std::cout << "[Step 2] Creating OpenXR session with required extensions..." << std::endl;

    std::vector<std::shared_ptr<core::ITracker>> trackers = { tracker };
    auto required_extensions = core::DeviceIOSession::get_required_extensions(trackers);

    auto oxr_session = std::make_shared<core::OpenXRSession>("FullBodyPrinter", required_extensions);

    std::cout << "  OpenXR session created" << std::endl;

    // Step 3: Create DeviceIOSession with the tracker
    std::cout << "[Step 3] Creating DeviceIOSession..." << std::endl;

    std::unique_ptr<core::DeviceIOSession> session;
    session = core::DeviceIOSession::run(trackers, oxr_session->get_handles());

    // Step 4: Read samples by updating the session
    std::cout << "[Step 4] Reading samples..." << std::endl;

    // Bound the loop so it cannot spin forever when no samples ever arrive (limp mode): a
    // healthy session delivers a sample almost every tick, so twice the sample budget is ample.
    constexpr size_t MAX_TICKS = 2 * MAX_SAMPLES;

    size_t received_count = 0;
    size_t tick_count = 0;
    while (received_count < MAX_SAMPLES && tick_count < MAX_TICKS)
    {
        // Update session (this calls update on all trackers).
        session->update();

        // Print current data if available. tracked.data is null only in limp mode (body tracking
        // unsupported); a supported-but-untracked body still delivers data with valid=0/24 joints.
        const auto& tracked = tracker->get_body_pose(*session);
        if (tracked.data)
        {
            print_body_pose(*tracked.data, received_count++);
        }
        else if (tick_count % 30 == 0)
        {
            // Heartbeat once per second (~30th tick at 30 Hz) so an inactive session is visible
            // instead of silent. Same literal as record_full_body.cpp so both siblings report
            // this state identically.
            std::cout << "[body tracking inactive]" << std::endl;
        }
        ++tick_count;

        // Tick at ~30 Hz.
        std::this_thread::sleep_for(std::chrono::milliseconds(33));
    }

    if (received_count == 0)
    {
        std::cout << "\nNo body tracking samples received — body tracking is inactive or unsupported." << std::endl;
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
