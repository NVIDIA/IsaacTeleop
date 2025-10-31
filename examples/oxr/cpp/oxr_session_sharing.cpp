#include <oxr/oxr_manager.hpp>
#include <oxr/oxr_handtracker.hpp>
#include <oxr/oxr_headtracker.hpp>
#include <iostream>
#include <memory>
#include <thread>
#include <chrono>

int main() {
    std::cout << "OpenXR Session Sharing Example" << std::endl;
    std::cout << "================================" << std::endl;
    std::cout << std::endl;
    
    // Create Manager 1 with hand tracking
    std::cout << "[Manager 1] Creating with HandTracker..." << std::endl;
    auto hand_tracker1 = std::make_shared<oxr::HandTracker>();
    
    oxr::OpenXRManager manager1;
    manager1.add_tracker(hand_tracker1);
    
    if (!manager1.initialize("SessionSharingExample")) {
        std::cerr << "Failed to initialize manager 1" << std::endl;
        return 1;
    }
    
    std::cout << "✓ Manager 1 initialized" << std::endl;
    std::cout << std::endl;
    
    // Get handles from Manager 1
    XrInstance instance = manager1.get_instance();
    XrSession session = manager1.get_session();
    XrSpace space = manager1.get_space();
    
    std::cout << "[Session Sharing] Got handles from Manager 1:" << std::endl;
    std::cout << "  Instance: " << instance << std::endl;
    std::cout << "  Session:  " << session << std::endl;
    std::cout << "  Space:    " << space << std::endl;
    std::cout << std::endl;
    
    // Create Manager 2 using same session
    std::cout << "[Manager 2] Creating with HeadTracker using shared session..." << std::endl;
    auto head_tracker2 = std::make_shared<oxr::HeadTracker>();
    
    oxr::OpenXRManager manager2;
    manager2.add_tracker(head_tracker2);
    
    if (!manager2.initialize("Manager2Shared", instance, session, space)) {
        std::cerr << "Failed to initialize manager 2 with external session" << std::endl;
        return 1;
    }
    
    std::cout << "✓ Manager 2 initialized with shared session" << std::endl;
    std::cout << std::endl;
    
    // Update both managers
    std::cout << "[Update Test] Updating both managers (10 frames)..." << std::endl;
    
    for (int i = 0; i < 10; ++i) {
        // Manager 1 does event polling (it owns the session)
        if (!manager1.update()) {
            std::cerr << "Manager 1 update failed" << std::endl;
            break;
        }
        
        // Manager 2 just updates its trackers
        if (!manager2.update()) {
            std::cerr << "Manager 2 update failed" << std::endl;
            break;
        }
        
        // Get data from both
        const auto& left = hand_tracker1->get_left_hand();
        const auto& head = head_tracker2->get_head();
        
        if (i % 3 == 0) {
            std::cout << "Frame " << i << ": "
                      << "Hands=" << (left.is_active ? "ACTIVE" : "INACTIVE") << " | "
                      << "Head=" << (head.is_valid ? "VALID" : "INVALID") << std::endl;
        }
        
        std::this_thread::sleep_for(std::chrono::milliseconds(16));
    }
    
    std::cout << std::endl;
    std::cout << "✓ Both managers working with shared session!" << std::endl;
    std::cout << std::endl;
    
    // Cleanup
    std::cout << "[Cleanup]" << std::endl;
    std::cout << "  Shutting down Manager 2 (doesn't own session)..." << std::endl;
    manager2.shutdown();
    
    std::cout << "  Shutting down Manager 1 (owns session)..." << std::endl;
    manager1.shutdown();
    
    std::cout << std::endl;
    std::cout << "Session sharing test complete!" << std::endl;
    
    return 0;
}

