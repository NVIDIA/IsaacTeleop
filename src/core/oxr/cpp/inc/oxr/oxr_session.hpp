#pragma once

#include <openxr/openxr.h>
#include <memory>
#include <string>
#include <vector>

namespace oxr {

// Wrapper for OpenXR session handles
struct OpenXRSessionHandles {
    XrInstance instance;
    XrSession session;
    XrSpace space;
    
    OpenXRSessionHandles()
        : instance(XR_NULL_HANDLE), session(XR_NULL_HANDLE), space(XR_NULL_HANDLE) {}
    
    OpenXRSessionHandles(XrInstance inst, XrSession sess, XrSpace sp)
        : instance(inst), session(sess), space(sp) {}
};

// OpenXR session management - creates and manages a headless OpenXR session
class OpenXRSession {
public:
    ~OpenXRSession();
    
    // Static factory method - returns nullptr on failure
    static std::shared_ptr<OpenXRSession> Create(
        const std::string& app_name, 
        const std::vector<std::string>& extensions = {});
    
    // Get session handles for use with trackers
    OpenXRSessionHandles get_handles() const;

private:
    // Private constructor - use Create() instead
    OpenXRSession();
    
    // Initialization methods
    bool create_instance(const std::string& app_name, const std::vector<std::string>& extensions);
    bool create_system();
    bool create_session();
    bool create_reference_space();
    
    XrInstance instance_;
    XrSystemId system_id_;
    XrSession session_;
    XrSpace space_;
};

} // namespace oxr
