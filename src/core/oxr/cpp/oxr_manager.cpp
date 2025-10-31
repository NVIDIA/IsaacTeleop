#include "inc/oxr/oxr_manager.hpp"

#include <iostream>
#include <set>
#include <time.h>

namespace oxr {

OpenXRManager::OpenXRManager()
    : initialized_(false),
      owns_session_(false),
      external_instance_(XR_NULL_HANDLE),
      external_session_(XR_NULL_HANDLE),
      external_space_(XR_NULL_HANDLE) {
}

OpenXRManager::~OpenXRManager() {
    shutdown();
}

void OpenXRManager::add_tracker(std::shared_ptr<ITracker> tracker) {
    if (initialized_) {
        std::cerr << "Cannot add trackers after initialization" << std::endl;
        return;
    }
    trackers_.push_back(tracker);
}

std::vector<std::string> OpenXRManager::get_required_extensions() const {
    std::set<std::string> all_extensions;
    
    // Required for getting the time without a frame loop.
    all_extensions.insert("XR_KHR_convert_timespec_time");
    
    // Add extensions from each tracker
    for (const auto& tracker : trackers_) {
        auto extensions = tracker->get_required_extensions();
        for (const auto& ext : extensions) {
            all_extensions.insert(ext);
        }
    }
    
    // Convert set to vector
    return std::vector<std::string>(all_extensions.begin(), all_extensions.end());
}

bool OpenXRManager::initialize(const std::string& app_name,
                                XrInstance external_instance,
                                XrSession external_session,
                                XrSpace external_space) {
    if (initialized_) {
        std::cerr << "Already initialized" << std::endl;
        return false;
    }
    
    XrInstance instance;
    XrSession xr_session;
    XrSpace base_space;
    
    // Check if using external session or creating new one
    bool use_external = (external_instance != XR_NULL_HANDLE &&
                         external_session != XR_NULL_HANDLE &&
                         external_space != XR_NULL_HANDLE);
    
    if (use_external) {
        // Use provided external session
        std::cout << "Using external OpenXR session" << std::endl;
        external_instance_ = external_instance;
        external_session_ = external_session;
        external_space_ = external_space;
        owns_session_ = false;
        
        instance = external_instance;
        xr_session = external_session;
        base_space = external_space;
    } else {
        // Create our own session
        std::cout << "Creating new OpenXR session" << std::endl;
        
        // Get required extensions (use the public method)
        auto all_extensions = get_required_extensions();

        // Always add headless/overlay extensions if we are creating our own session.
        all_extensions.push_back("XR_MND_headless");
        all_extensions.push_back("XR_EXTX_overlay");
        
        std::cout << "Initializing OpenXR with " << all_extensions.size() << " extensions:" << std::endl;
        for (const auto& ext : all_extensions) {
            std::cout << "  - " << ext << std::endl;
        }
        
        // Create session with collected extensions
        session_ = std::make_unique<OpenXRSession>();
        if (!session_->initialize(app_name, all_extensions)) {
            std::cerr << "Failed to initialize OpenXR session" << std::endl;
            return false;
        }
        
        // Wait for session to be ready
        int max_attempts = 100;
        while (!session_->is_session_running() && max_attempts-- > 0) {
            session_->poll_events();
            if (session_->get_session_state() == XR_SESSION_STATE_EXITING ||
                session_->get_session_state() == XR_SESSION_STATE_LOSS_PENDING) {
                std::cerr << "Session exiting or loss pending" << std::endl;
                return false;
            }
        }
        
        if (!session_->is_session_running()) {
            std::cerr << "Session never became ready" << std::endl;
            return false;
        }
        
        owns_session_ = true;
        instance = session_->get_instance();
        xr_session = session_->get_session();
        base_space = session_->get_space();
    }
    
    // Initialize all trackers
    for (auto& tracker : trackers_) {
        if (!tracker->initialize(instance, xr_session, base_space)) {
            std::cerr << "Failed to initialize tracker: " << tracker->get_name() << std::endl;
            return false;
        }
    }
    
    initialized_ = true;
    std::cout << "OpenXRManager initialized with " << trackers_.size() << " trackers"
              << (owns_session_ ? " (owns session)" : " (external session)") << std::endl;
    return true;
}

void OpenXRManager::shutdown() {
    if (!initialized_) {
        return;
    }
    
    // Cleanup all trackers BEFORE destroying session/instance
    // This ensures tracker OpenXR resources are destroyed while instance is still valid
    for (auto& tracker : trackers_) {
        tracker->cleanup();
    }
    trackers_.clear();
    
    // Cleanup session only if we own it
    if (owns_session_) {
        session_.reset();
    }
    
    initialized_ = false;
    owns_session_ = false;
}

bool OpenXRManager::update() {
    if (!initialized_) {
        return false;
    }
    
    XrTime current_time;
    
    if (owns_session_) {
        // We own the session, so we manage polling and timing
        if (!session_->poll_events()) {
            return false;
        }
        
        if (!session_->is_session_running()) {
            return false;
        }
        
        if (!session_->update_time()) {
            return false;
        }
        
        current_time = session_->get_predicted_time();
    } else {
        // External session - just get current time ourselves
        // The owner of the session handles polling/events
        struct timespec ts;
        clock_gettime(CLOCK_MONOTONIC, &ts);
        
        // We need the convert function - get it from instance
        PFN_xrConvertTimespecTimeToTimeKHR pfn_convert;
        xrGetInstanceProcAddr(external_instance_, "xrConvertTimespecTimeToTimeKHR",
            reinterpret_cast<PFN_xrVoidFunction*>(&pfn_convert));
        
        if (pfn_convert) {
            pfn_convert(external_instance_, &ts, &current_time);
        } else {
            std::cerr << "Cannot get time with external session" << std::endl;
            return false;
        }
    }
    
    // Update all trackers
    for (auto& tracker : trackers_) {
        if (!tracker->update(current_time)) {
            std::cerr << "Warning: tracker " << tracker->get_name() << " update failed" << std::endl;
        }
    }
    
    return true;
}

XrInstance OpenXRManager::get_instance() const {
    if (owns_session_ && session_) {
        return session_->get_instance();
    }
    return external_instance_;
}

XrSession OpenXRManager::get_session() const {
    if (owns_session_ && session_) {
        return session_->get_session();
    }
    return external_session_;
}

XrSpace OpenXRManager::get_space() const {
    if (owns_session_ && session_) {
        return session_->get_space();
    }
    return external_space_;
}

} // namespace oxr


