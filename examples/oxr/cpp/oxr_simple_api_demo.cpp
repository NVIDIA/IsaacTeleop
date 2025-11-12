#include <oxr/oxr_session.hpp>
#include <xrio/handtracker.hpp>
#include <xrio/headtracker.hpp>
#include <xrio/teleop_session.hpp>

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
    auto hand_tracker = std::make_shared<oxr::HandTracker>();
    auto head_tracker = std::make_shared<oxr::HeadTracker>();

    std::cout << "  ✓ Created " << hand_tracker->get_name() << std::endl;
    std::cout << "  ✓ Created " << head_tracker->get_name() << std::endl;

    // Check initialization status before session is created
    std::cout << "  Status before session:" << std::endl;
    std::cout << "    Hand tracker initialized: " << (hand_tracker->is_initialized() ? "YES" : "NO") << std::endl;
    std::cout << "    Head tracker initialized: " << (head_tracker->is_initialized() ? "YES" : "NO") << std::endl;
    std::cout << std::endl;

    // Note: At this point, external users CANNOT call:
    // - hand_tracker->initialize()  // protected - not visible!
    // - hand_tracker->update()      // protected - not visible!
    // - hand_tracker->cleanup()     // protected - not visible!

    // Step 2: External user adds trackers to builder
    std::cout << "[Step 2] Adding trackers to builder..." << std::endl;
    oxr::TeleopSessionBuilder builder;
    builder.add_tracker(hand_tracker);
    builder.add_tracker(head_tracker);

    std::cout << "  ✓ Trackers added" << std::endl;
    std::cout << std::endl;

    // Step 3: External user queries required extensions (public API)
    std::cout << "[Step 3] Querying required extensions..." << std::endl;
    auto required_extensions = builder.get_required_extensions();

    std::cout << "  Required extensions:" << std::endl;
    for (const auto& ext : required_extensions)
    {
        std::cout << "    - " << ext << std::endl;
    }
    std::cout << std::endl;

    // Step 4: External user creates session (manager handles internal lifecycle)
    std::cout << "[Step 4] Creating session..." << std::endl;

    // Create OpenXR session with required extensions
    auto oxr_session = oxr::OpenXRSession::Create("SimpleAPIDemo", required_extensions);
    if (!oxr_session)
    {
        std::cerr << "  ✗ Failed to create OpenXR session" << std::endl;
        return 1;
    }

    auto handles = oxr_session->get_handles();
    auto session = builder.build(handles);
    if (!session)
    {
        std::cerr << "  ✗ Failed to create teleop session" << std::endl;
        return 1;
    }

    std::cout << "  ✓ Session created (internal initialization handled by manager)" << std::endl;

    // Check initialization status after session is created
    std::cout << "  Status after session:" << std::endl;
    std::cout << "    Hand tracker initialized: " << (hand_tracker->is_initialized() ? "YES" : "NO") << std::endl;
    std::cout << "    Head tracker initialized: " << (head_tracker->is_initialized() ? "YES" : "NO") << std::endl;
    std::cout << std::endl;

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

        // Check initialization before using trackers (good practice)
        if (!hand_tracker->is_initialized() || !head_tracker->is_initialized())
        {
            std::cerr << "Trackers not initialized!" << std::endl;
            break;
        }

        // External user only uses public query methods
        const auto& left = hand_tracker->get_left_hand();
        const auto& right = hand_tracker->get_right_hand();
        const auto& head = head_tracker->get_head();

        std::cout << "Frame " << i << ":" << std::endl;
        std::cout << "  Left hand:  " << (left.is_active ? "ACTIVE" : "INACTIVE") << std::endl;
        std::cout << "  Right hand: " << (right.is_active ? "ACTIVE" : "INACTIVE") << std::endl;
        std::cout << "  Head pose:  " << (head.is_valid ? "VALID" : "INVALID") << std::endl;

        if (head.is_valid)
        {
            std::cout << "    Position: [" << head.position[0] << ", " << head.position[1] << ", " << head.position[2]
                      << "]" << std::endl;
        }
        std::cout << std::endl;
    }

    std::cout << "✓ Clean public API demo complete!" << std::endl;
    std::cout << std::endl;
    std::cout << "Summary:" << std::endl;
    std::cout << "  ✓ External users only see public API methods" << std::endl;
    std::cout << "  ✓ is_initialized() available to check tracker status" << std::endl;
    std::cout << "  ✓ Lifecycle methods (initialize/update/cleanup) are hidden" << std::endl;
    std::cout << "  ✓ Session manages internal lifecycle automatically" << std::endl;
    std::cout << std::endl;

    return 0;
}
