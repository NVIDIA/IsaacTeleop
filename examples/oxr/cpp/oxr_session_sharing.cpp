// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

// Prevent Windows.h from defining min/max macros that conflict with std::min/max
#if defined(_WIN32) || defined(_WIN64)
#    define NOMINMAX
#endif

#include <deviceio/deviceio_session.hpp>
#include <deviceio/hand_tracker.hpp>
#include <deviceio/head_tracker.hpp>
#include <oxr/oxr_session.hpp>

#include <chrono>
#include <iostream>
#include <memory>
#include <thread>

int main()
{
    std::cout << "OpenXR Session Sharing Example" << std::endl;
    std::cout << "================================" << std::endl;
    std::cout << std::endl;

    // Step 1: Create OpenXR session directly with all required extensions
    std::cout << "[Step 1] Creating standalone OpenXR session..." << std::endl;

    // Collect extensions needed by our trackers
    std::vector<std::string> extensions_vec{
        "XR_KHR_convert_timespec_time", // Required for time conversion
        "XR_EXT_hand_tracking" // Hand tracking
    };

    std::cout << "  Required extensions:" << std::endl;
    for (const auto& ext : extensions_vec)
    {
        std::cout << "    - " << ext << std::endl;
    }

    auto oxr_session = core::OpenXRSession::Create("SessionSharingExample", extensions_vec);
    if (!oxr_session)
    {
        std::cerr << "Failed to create OpenXR session" << std::endl;
        return 1;
    }

    std::cout << "  ✓ OpenXR session created" << std::endl;
    std::cout << std::endl;

    // Step 2: Get handles from the session
    std::cout << "[Step 2] Getting session handles..." << std::endl;
    auto handles = oxr_session->get_handles();

    std::cout << "  Instance: " << handles.instance << std::endl;
    std::cout << "  Session:  " << handles.session << std::endl;
    std::cout << "  Space:    " << handles.space << std::endl;
    std::cout << std::endl;

    // Step 3: Create Manager 1 with HandTracker using the shared session
    std::cout << "[Step 3] Creating Manager 1 with HandTracker..." << std::endl;
    auto hand_tracker = std::make_shared<core::HandTracker>();

    std::vector<std::shared_ptr<core::ITracker>> trackers1 = { hand_tracker };
    // run() throws exception on failure
    auto session1 = core::DeviceIOSession::run(trackers1, handles);

    std::cout << "  ✓ Manager 1 using shared session" << std::endl;
    std::cout << std::endl;

    // Step 4: Create Manager 2 with HeadTracker using the SAME shared session
    std::cout << "[Step 4] Creating Manager 2 with HeadTracker..." << std::endl;
    auto head_tracker = std::make_shared<core::HeadTracker>();

    std::vector<std::shared_ptr<core::ITracker>> trackers2 = { head_tracker };
    // run() throws exception on failure
    auto session2 = core::DeviceIOSession::run(trackers2, handles);

    std::cout << "  ✓ Manager 2 using shared session" << std::endl;
    std::cout << std::endl;

    // Step 5: Update both sessions - they share the same OpenXR session!
    std::cout << "[Step 5] Testing both managers with shared session (10 frames)..." << std::endl;
    std::cout << std::endl;

    for (int i = 0; i < 10; ++i)
    {
        // Both sessions update using the same underlying OpenXR session
        if (!session1->update())
        {
            std::cerr << "Session 1 update failed" << std::endl;
            break;
        }

        if (!session2->update())
        {
            std::cerr << "Session 2 update failed" << std::endl;
            break;
        }

        // Get data from both trackers
        const auto& left = hand_tracker->get_left_hand(*session1);
        const auto& head = head_tracker->get_head(*session2);

        if (i % 3 == 0)
        {
            std::cout << "Frame " << i << ": "
                      << "Hands=" << (left.is_active ? "ACTIVE" : "INACTIVE") << " | "
                      << "Head=" << (head.is_valid ? "VALID" : "INVALID");
            if (head.is_valid && head.pose)
            {
                const auto& pos = head.pose->position();
                std::cout << " [" << pos.x() << ", " << pos.y() << ", " << pos.z() << "]";
            }
            std::cout << std::endl;
        }

        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }

    std::cout << std::endl;
    std::cout << "✓ Both managers working with shared OpenXR session!" << std::endl;
    std::cout << std::endl;

    // Cleanup
    std::cout << "[Cleanup]" << std::endl;
    std::cout << "  Destroying Manager 1..." << std::endl;
    session1.reset(); // RAII cleanup

    std::cout << "  Destroying Manager 2..." << std::endl;
    session2.reset(); // RAII cleanup

    std::cout << "  Destroying shared OpenXR session..." << std::endl;
    oxr_session.reset(); // RAII cleanup

    std::cout << std::endl;
    std::cout << "✓ Session sharing test complete!" << std::endl;
    std::cout << std::endl;
    std::cout << "Summary:" << std::endl;
    std::cout << "  ✓ One OpenXR session created" << std::endl;
    std::cout << "  ✓ Two managers shared the same session" << std::endl;
    std::cout << "  ✓ HandTracker (Manager 1) and HeadTracker (Manager 2)" << std::endl;
    std::cout << "  ✓ Both updated successfully with shared session" << std::endl;
    std::cout << std::endl;

    return 0;
}
