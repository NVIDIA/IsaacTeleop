// SPDX-FileCopyrightText: Copyright (c) 2025 NVIDIA CORPORATION & AFFILIATES. All rights reserved.
// SPDX-License-Identifier: Apache-2.0

#include <deviceio/deviceio_session.hpp>
#include <deviceio/hand_tracker.hpp>
#include <deviceio/head_tracker.hpp>
#include <oxr/oxr_session.hpp>

#include <iostream>
#include <memory>

/**
 * Simple API Demo - demonstrates the clean public API
 *
 * External users only see:
 * - get_head() / get_left_hand() / get_right_hand()
 * - get_name() / get_required_extensions()
 *
 * Internal lifecycle methods (initialize, update, cleanup) are hidden!
 */

int main()
{
    std::cout << "OpenXR Simple API Demo" << std::endl;
    std::cout << "======================" << std::endl;
    std::cout << std::endl;

    // Step 1: External user creates trackers (only public API visible)
    std::cout << "[Step 1] Creating trackers..." << std::endl;
    auto hand_tracker = std::make_shared<core::HandTracker>();
    auto head_tracker = std::make_shared<core::HeadTracker>();

    std::cout << "  ✓ Created " << hand_tracker->get_name() << std::endl;
    std::cout << "  ✓ Created " << head_tracker->get_name() << std::endl;

    // Note: At this point, external users CANNOT call:
    // - hand_tracker->initialize()  // protected - not visible!
    // - hand_tracker->update()      // protected - not visible!
    // - hand_tracker->cleanup()     // protected - not visible!

    // Step 2: External user queries required extensions (public API)
    std::cout << "[Step 2] Querying required extensions..." << std::endl;
    std::vector<std::shared_ptr<core::ITracker>> trackers = { hand_tracker, head_tracker };
    auto required_extensions = core::DeviceIOSession::get_required_extensions(trackers);

    std::cout << "  Required extensions:" << std::endl;
    for (const auto& ext : required_extensions)
    {
        std::cout << "    - " << ext << std::endl;
    }
    std::cout << std::endl;

    // Step 3: External user creates OpenXR session
    std::cout << "[Step 3] Creating OpenXR session..." << std::endl;

    // Create OpenXR session with required extensions
    auto oxr_session = core::OpenXRSession::Create("SimpleAPIDemo", required_extensions);
    if (!oxr_session)
    {
        std::cerr << "  ✗ Failed to create OpenXR session" << std::endl;
        return 1;
    }

    std::cout << "  ✓ OpenXR session created" << std::endl;
    std::cout << std::endl;

    // Step 4: Run deviceio session with trackers (handles internal lifecycle, throws on failure)
    std::cout << "[Step 4] Running deviceio session with trackers..." << std::endl;

    auto handles = oxr_session->get_handles();
    auto session = core::DeviceIOSession::run(trackers, handles);

    std::cout << "  ✓ Session created (internal initialization handled automatically)" << std::endl;

    // Step 5: External user updates and queries data (public API only!)
    std::cout << "[Step 5] Querying tracker data..." << std::endl;
    std::cout << std::endl;

    for (int i = 0; i < 5; ++i)
    {
        // Session handles internal update() calls to trackers
        if (!session->update())
        {
            std::cerr << "Update failed" << std::endl;
            break;
        }

        // External user only uses public query methods
        const auto& left = hand_tracker->get_left_hand(*session);
        const auto& right = hand_tracker->get_right_hand(*session);
        const auto& head = head_tracker->get_head(*session);

        std::cout << "Frame " << i << ":" << std::endl;
        std::cout << "  Left hand:  " << (left.is_active ? "ACTIVE" : "INACTIVE") << std::endl;
        std::cout << "  Right hand: " << (right.is_active ? "ACTIVE" : "INACTIVE") << std::endl;
        std::cout << "  Head pose:  " << (head.is_valid ? "VALID" : "INVALID") << std::endl;

        if (head.is_valid && head.pose)
        {
            const auto& pos = head.pose->position();
            std::cout << "    Position: [" << pos.x() << ", " << pos.y() << ", " << pos.z() << "]" << std::endl;
        }
        std::cout << std::endl;
    }

    std::cout << "✓ Clean public API demo complete!" << std::endl;
    std::cout << std::endl;
    std::cout << "Summary:" << std::endl;
    std::cout << "  ✓ External users only see public API methods" << std::endl;
    std::cout << "  ✓ Lifecycle methods (initialize/update/cleanup) are hidden" << std::endl;
    std::cout << "  ✓ Session manages internal lifecycle automatically" << std::endl;
    std::cout << std::endl;

    return 0;
}
