#pragma once

#include "oxr_tracker.hpp"
#include "oxr_session.hpp"
#include <memory>
#include <vector>
#include <string>

namespace oxr {

// OpenXR Manager - coordinates session and multiple trackers
class OpenXRManager {
public:
    OpenXRManager();
    ~OpenXRManager();
    
    // Add trackers before initialization
    void add_tracker(std::shared_ptr<ITracker> tracker);
    
    // Get all required extensions from added trackers
    // Call this after adding trackers but before initialize()
    std::vector<std::string> get_required_extensions() const;
    
    // Initialize OpenXR with all added trackers
    // If instance/session/space are null, creates new session
    // Otherwise uses provided external session
    bool initialize(const std::string& app_name = "OpenXR",
                    XrInstance external_instance = XR_NULL_HANDLE,
                    XrSession external_session = XR_NULL_HANDLE,
                    XrSpace external_space = XR_NULL_HANDLE);
    
    // Shutdown and cleanup
    void shutdown();
    
    // Check if initialized
    bool is_initialized() const { return initialized_; }
    
    // Update all trackers
    bool update();
    
    // Get OpenXR handles (for sharing with other managers)
    XrInstance get_instance() const;
    XrSession get_session() const;
    XrSpace get_space() const;
    
    // Get the session object (for advanced use)
    OpenXRSession* get_session_object() { return session_.get(); }

private:
    bool initialized_;
    bool owns_session_;  // True if we created the session, false if external
    std::unique_ptr<OpenXRSession> session_;
    
    // External session handles (if provided)
    XrInstance external_instance_;
    XrSession external_session_;
    XrSpace external_space_;
    
    std::vector<std::shared_ptr<ITracker>> trackers_;
};

} // namespace oxr


