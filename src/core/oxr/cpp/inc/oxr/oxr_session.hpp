#pragma once

#include <openxr/openxr.h>
#include <string>
#include <vector>
#include <time.h>

// Define time conversion function pointer type if not in headers
typedef XrResult (XRAPI_PTR *PFN_xrConvertTimespecTimeToTimeKHR)(XrInstance instance, const struct timespec* timespecTime, XrTime* time);

namespace oxr {

// OpenXR session management for headless mode
class OpenXRSession {
public:
    OpenXRSession();
    ~OpenXRSession();

    bool initialize(const std::string& app_name, const std::vector<std::string>& extensions = {});
    void shutdown();
    
    bool poll_events();
    bool update_time();  // Get current XR time using clock_gettime + xrConvertTimespecTimeToTimeKHR
    
    XrInstance get_instance() const { return instance_; }
    XrSession get_session() const { return session_; }
    XrSpace get_space() const { return space_; }
    XrSystemId get_system_id() const { return system_id_; }
    XrSessionState get_session_state() const { return session_state_; }
    XrTime get_predicted_time() const { return predicted_time_; }
    
    bool is_session_running() const { return session_state_ == XR_SESSION_STATE_FOCUSED || 
                                              session_state_ == XR_SESSION_STATE_VISIBLE ||
                                              session_state_ == XR_SESSION_STATE_SYNCHRONIZED; }

private:
    bool create_instance(const std::string& app_name, const std::vector<std::string>& extensions);
    bool create_system();
    bool create_session();
    bool create_reference_space();
    
    XrInstance instance_;
    XrSystemId system_id_;
    XrSession session_;
    XrSpace space_;
    XrSessionState session_state_;
    XrTime predicted_time_;
    bool session_running_;
    
    // Extension function pointer for time conversion
    PFN_xrConvertTimespecTimeToTimeKHR pfn_convert_timespec_;
};

} // namespace oxr
